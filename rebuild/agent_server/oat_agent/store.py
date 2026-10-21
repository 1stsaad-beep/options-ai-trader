"""SQLite store (one file on the Railway volume). Journal and events are append-only."""
from __future__ import annotations
import datetime as dt
import json
import sqlite3
import threading
import uuid
from .models import GuardState

SCHEMA = """
create table if not exists kv(key text primary key, value text not null);
create table if not exists journal(id text primary key, ts text not null, kind text not null, sym text, body text not null);
create table if not exists events(seq integer primary key autoincrement, ts text not null, kind text not null, sym text, body text not null);
create table if not exists alerts(id text primary key, sym text not null, cond text not null, note text, created text not null,
                                  triggered_at text, active integer not null default 1);
create table if not exists positions_meta(occ text primary key, sym text not null, journal_id text not null,
                                          invalidation real not null, entry_ts text not null, body text not null);
create table if not exists costs(seq integer primary key autoincrement, ts text not null, model text, input_tokens integer,
                                 output_tokens integer, usd real not null, purpose text);
create table if not exists snapshots(id text primary key, ts text not null, journal_id text, kind text not null,
                                     model_id text, prompt_version text, blob blob not null);
create table if not exists snapshot_links(sid text not null, journal_id text not null, primary key(sid, journal_id));
create table if not exists shadow(journal_id text primary key, ts text not null, status text not null, body text not null);
create trigger if not exists snapshots_no_update before update on snapshots begin select raise(abort, 'snapshots are append-only'); end;
create trigger if not exists snapshots_no_delete before delete on snapshots begin select raise(abort, 'snapshots are append-only'); end;
create trigger if not exists journal_no_update before update on journal begin select raise(abort, 'journal is append-only'); end;
create trigger if not exists journal_no_delete before delete on journal begin select raise(abort, 'journal is append-only'); end;
create trigger if not exists events_no_update before update on events begin select raise(abort, 'events are append-only'); end;
create trigger if not exists events_no_delete before delete on events begin select raise(abort, 'events are append-only'); end;
"""


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat()


def parse(s):
    return None if s is None else dt.datetime.fromisoformat(s)


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def close(self):
        with self.lock:
            self.db.close()

    def __del__(self):
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass

    def _x(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    # ---- kv
    def get(self, key, default=None):
        r = self._x("select value from kv where key=?", (key,)).fetchone()
        return default if r is None else json.loads(r[0])

    def put(self, key, value):
        self._x("insert into kv(key,value) values(?,?) on conflict(key) do update set value=excluded.value", (key, json.dumps(value)))

    # ---- guard state
    def guard_state(self) -> GuardState:
        g = self.get("guard_state", {})
        return GuardState(day_key=g.get("day_key"), day_start_equity=g.get("day_start_equity"),
                          orders_day_key=g.get("orders_day_key"), orders_today=g.get("orders_today", 0),
                          last_trade_at={k: parse(v) for k, v in g.get("last_trade_at", {}).items()},
                          paused=g.get("paused", False))

    def save_guard_state(self, st: GuardState):
        self.put("guard_state", dict(day_key=st.day_key, day_start_equity=st.day_start_equity, orders_day_key=st.orders_day_key,
                                     orders_today=st.orders_today, last_trade_at={k: iso(v) for k, v in st.last_trade_at.items()},
                                     paused=st.paused))

    # ---- journal / events
    def journal_add(self, now, kind, body, sym=None, jid=None) -> str:
        jid = jid or f"J{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        self._x("insert into journal(id,ts,kind,sym,body) values(?,?,?,?,?)", (jid, iso(now), kind, sym, json.dumps(body, ensure_ascii=False)))
        return jid

    def journal_exists(self, jid) -> bool:
        return self._x("select 1 from journal where id=?", (jid,)).fetchone() is not None

    def journal(self, limit=200):
        return [dict(id=r[0], ts=r[1], kind=r[2], sym=r[3], body=json.loads(r[4]))
                for r in self._x("select id,ts,kind,sym,body from journal order by ts desc limit ?", (limit,))]

    def event(self, now, kind, body, sym=None):
        self._x("insert into events(ts,kind,sym,body) values(?,?,?,?)", (iso(now), kind, sym, json.dumps(body, ensure_ascii=False)))

    def event_safe(self, kind, body, sym=None):
        import datetime as _dt
        self.event(_dt.datetime.now(_dt.timezone.utc), kind, body, sym)

    def events(self, kind=None, limit=500):
        q = "select ts,kind,sym,body from events" + (" where kind=?" if kind else "") + " order by seq desc limit ?"
        return [dict(ts=r[0], kind=r[1], sym=r[2], body=json.loads(r[3])) for r in self._x(q, ((kind, limit) if kind else (limit,)))]

    # ---- alerts
    def alert_add(self, now, sym, cond, note):
        aid = f"A{uuid.uuid4().hex[:10]}"
        self._x("insert into alerts(id,sym,cond,note,created) values(?,?,?,?,?)", (aid, sym, cond, note, iso(now)))
        return aid

    def alerts_active(self, sym=None):
        q = "select id,sym,cond,note,created from alerts where active=1" + (" and sym=?" if sym else "")
        return [dict(id=r[0], sym=r[1], cond=r[2], note=r[3], created=r[4]) for r in self._x(q, (sym,) if sym else ())]

    def alert_fired(self, aid, now):
        self._x("update alerts set active=0, triggered_at=? where id=?", (iso(now), aid))

    # ---- position meta (invalidation + journal link per held contract)
    def meta_put(self, occ, sym, journal_id, invalidation, entry_ts, body=None):
        self._x("insert into positions_meta(occ,sym,journal_id,invalidation,entry_ts,body) values(?,?,?,?,?,?) "
                "on conflict(occ) do update set journal_id=excluded.journal_id, invalidation=excluded.invalidation",
                (occ, sym, journal_id, invalidation, iso(entry_ts), json.dumps(body or {})))

    def meta(self, occ):
        r = self._x("select occ,sym,journal_id,invalidation,entry_ts,body from positions_meta where occ=?", (occ,)).fetchone()
        return None if r is None else dict(occ=r[0], sym=r[1], journal_id=r[2], invalidation=r[3], entry_ts=r[4], body=json.loads(r[5]))

    def meta_drop(self, occ):
        self._x("delete from positions_meta where occ=?", (occ,))

    # ---- decision snapshots (gzip JSON, append-only, replayable)
    def snapshot_add(self, now, kind, payload, journal_id=None, model_id=None, prompt_version=None) -> str:
        import gzip
        sid = f"S{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        blob = gzip.compress(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True).encode(), mtime=0)
        self._x("insert into snapshots(id,ts,journal_id,kind,model_id,prompt_version,blob) values(?,?,?,?,?,?,?)",
                (sid, iso(now), journal_id, kind, model_id, prompt_version, blob))
        return sid

    def snapshot_get(self, sid):
        import gzip
        r = self._x("select id,ts,journal_id,kind,model_id,prompt_version,blob from snapshots where id=?", (sid,)).fetchone()
        if r is None: return None
        return dict(id=r[0], ts=r[1], journal_id=r[2], kind=r[3], model_id=r[4], prompt_version=r[5],
                    payload=json.loads(gzip.decompress(r[6])))

    def snapshot_link(self, sid, journal_id):
        self._x("insert or ignore into snapshot_links(sid, journal_id) values(?,?)", (sid, journal_id))

    def snapshots_for(self, journal_id):
        return [r[0] for r in self._x("select id from snapshots where journal_id=? or id in (select sid from snapshot_links "
                                      "where journal_id=?) order by ts", (journal_id, journal_id))]

    # ---- shadow ledger (§11)
    def shadow_put(self, journal_id, now, status, body):
        self._x("insert into shadow(journal_id,ts,status,body) values(?,?,?,?) on conflict(journal_id) do update set "
                "status=excluded.status, body=excluded.body", (journal_id, iso(now), status, json.dumps(body, ensure_ascii=False, default=str)))

    def shadow_get(self, journal_id):
        r = self._x("select journal_id,ts,status,body from shadow where journal_id=?", (journal_id,)).fetchone()
        return None if r is None else dict(journal_id=r[0], ts=r[1], status=r[2], body=json.loads(r[3]))

    def shadows(self, status=None):
        q = "select journal_id,ts,status,body from shadow" + (" where status=?" if status else "") + " order by ts"
        return [dict(journal_id=r[0], ts=r[1], status=r[2], body=json.loads(r[3])) for r in self._x(q, (status,) if status else ())]

    # ---- costs (model + data spend of this agent)
    def cost_add(self, now, usd, model=None, input_tokens=0, output_tokens=0, purpose=None):
        self._x("insert into costs(ts,model,input_tokens,output_tokens,usd,purpose) values(?,?,?,?,?,?)",
                (iso(now), model, input_tokens, output_tokens, float(usd), purpose))

    def cost_since(self, t0: dt.datetime) -> float:
        return float(self._x("select coalesce(sum(usd),0) from costs where ts>=?", (iso(t0),)).fetchone()[0])
