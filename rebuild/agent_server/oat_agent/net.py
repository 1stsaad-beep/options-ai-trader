"""The only HTTP client of the service. Every request is checked against a host allow-list; the live trading host
is explicitly denied (hard rule: the live endpoint must be unreachable from this service)."""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from . import config


class ForbiddenHost(Exception):
    pass


def allowed_hosts(atlas_base_url: str | None = None):
    hosts = {urlsplit(u).hostname for u in (config.PAPER_TRADING_URL, config.MARKET_DATA_URL, config.ANTHROPIC_URL)}
    if atlas_base_url: hosts.add(urlsplit(atlas_base_url).hostname)
    return frozenset(h for h in hosts if h)


def check_url(url: str, allow) -> None:
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host in config.LIVE_TRADING_HOSTS:
        raise ForbiddenHost(f"live trading host is blocked: {host}")
    if p.scheme != "https":
        raise ForbiddenHost(f"https only: {url.split('?')[0]}")
    if host not in allow:
        raise ForbiddenHost(f"host not allowed: {host}")


class Http:
    def __init__(self, atlas_base_url: str | None = None, timeout: float = 15.0, opener=None):
        self.allow = allowed_hosts(atlas_base_url)
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def request(self, method: str, url: str, headers=None, body=None):
        check_url(url, self.allow)
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self._open(req, timeout=self.timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:  # noqa: BLE001
                return e.code, {"message": raw[:200].decode(errors="replace")}
