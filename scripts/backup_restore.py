"""Local SQLite snapshots with checksums and no-overwrite restore.

No network, database credentials, external commands or trading operations.
The online backup API copies committed SQLite state, including an active WAL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone


class BackupError(ValueError):
    """A safe failure which may be shown without database contents."""


def _regular(path: Path) -> Path:
    try:
        info = path.lstat()
    except OSError:
        raise BackupError("Input must be an existing regular file") from None
    if not stat.S_ISREG(info.st_mode):
        raise BackupError("Symlinks and non-regular input files are refused")
    return path.absolute()


def _destination(path: Path) -> Path:
    if not path.name or path.name in (".", ".."):
        raise BackupError("A new destination filename is required")
    if not path.parent.is_dir():
        raise BackupError("Create a private destination directory first")
    path = path.parent.resolve() / path.name
    for candidate in (path, manifest_path(path), Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
        if os.path.lexists(candidate):
            raise BackupError("Destination or companion file already exists; nothing is overwritten")
    return path


def manifest_path(path: Path) -> Path:
    return Path(str(path) + ".manifest.json")


def _temporary(parent: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".oat-snapshot-", dir=parent)
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    return Path(name)


def _digest(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _connect_readonly(path: Path, immutable: bool = False):
    # Immutable is only for a private standalone verified snapshot: ignore any
    # attacker-supplied WAL sidecar. Never use it for an active source database.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else ""), uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _integrity(path: Path):
    try:
        with closing(_connect_readonly(path, immutable=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackupError("SQLite integrity verification failed")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise BackupError("SQLite foreign key verification failed")
    except sqlite3.Error:
        raise BackupError("Input is not a valid standalone SQLite snapshot") from None


def _manifest(path: Path, operation: str, source_name: str) -> dict:
    digest, size = _digest(path)
    return {"format": "options-ai-trader-sqlite-snapshot", "version": 1,
            "operation": operation, "source_name": source_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": digest, "size_bytes": size, "integrity": "ok"}


def _sync(path: Path):
    with path.open("rb") as file:
        os.fsync(file.fileno())


def _publish(snapshot: Path, destination: Path, manifest: dict):
    """Hard-link publication is atomic and cannot replace an existing name."""
    manifest_temp = _temporary(destination.parent)
    published_manifest = False
    try:
        manifest_temp.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _sync(snapshot)
        _sync(manifest_temp)
        os.link(manifest_temp, manifest_path(destination))
        published_manifest = True
        os.link(snapshot, destination)
    except FileExistsError:
        # Remove only the manifest inode this call just created; never a file
        # supplied by the caller or another concurrent publisher.
        if published_manifest:
            try:
                if os.path.samefile(manifest_temp, manifest_path(destination)):
                    manifest_path(destination).unlink()
            except FileNotFoundError:
                pass
        raise BackupError("Concurrent destination creation detected; existing data preserved") from None
    finally:
        manifest_temp.unlink(missing_ok=True)
    # POSIX directory fsync makes published names durable where supported.
    descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup(source: str | Path, destination: str | Path) -> dict:
    source, destination = _regular(Path(source)), _destination(Path(destination))
    temporary = _temporary(destination.parent)
    try:
        try:
            deadline = time.monotonic() + 30
            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise BackupError("SQLite snapshot timed out without publishing data")
            with closing(_connect_readonly(source)) as src, closing(sqlite3.connect(temporary)) as target:
                src.backup(target, pages=256, progress=progress)
                target.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.Error:
            raise BackupError("SQLite online backup failed; no destination was published") from None
        _integrity(temporary)
        result = _manifest(temporary, "backup", source.name)
        _publish(temporary, destination, result)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def _read_manifest(snapshot: Path) -> dict:
    path = _regular(manifest_path(snapshot))
    try:
        if path.stat().st_size > 16384:
            raise BackupError("Oversized snapshot manifest")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("format") != "options-ai-trader-sqlite-snapshot"
                or type(value.get("version")) is not int or value["version"] != 1
                or value.get("integrity") != "ok"
                or type(value.get("size_bytes")) is not int or value["size_bytes"] < 100
                or not isinstance(value.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None):
            raise BackupError("Unsupported or malformed snapshot manifest")
        return value
    except (UnicodeError, json.JSONDecodeError, OSError):
        raise BackupError("Snapshot manifest could not be read safely") from None


def _verified_copy(snapshot: Path, temporary: Path) -> dict:
    expected = _read_manifest(snapshot)
    digest, size = hashlib.sha256(), 0
    # Inspect the bytes copied into our private file, not the mutable original
    # path after hashing. Restoring from an active database is unsupported.
    with snapshot.open("rb") as source, temporary.open("wb") as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
        raise BackupError("Snapshot SHA256/size mismatch; restore refused")
    _integrity(temporary)
    return expected


def verify(snapshot: str | Path) -> dict:
    snapshot = _regular(Path(snapshot))
    temporary = _temporary(snapshot.parent)
    try:
        return _verified_copy(snapshot, temporary)
    finally:
        temporary.unlink(missing_ok=True)


def restore(snapshot: str | Path, destination: str | Path) -> dict:
    snapshot, destination = _regular(Path(snapshot)), _destination(Path(destination))
    temporary = _temporary(destination.parent)
    try:
        original = _verified_copy(snapshot, temporary)
        result = _manifest(temporary, "restore", snapshot.name)
        result["restored_from_sha256"] = original["sha256"]
        _publish(temporary, destination, result)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for action in ("backup", "restore"):
        command = sub.add_parser(action)
        command.add_argument("source", type=Path)
        command.add_argument("destination", type=Path)
    command = sub.add_parser("verify")
    command.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "verify":
            result = verify(args.source)
        else:
            result = {"backup": backup, "restore": restore}[args.operation](args.source, args.destination)
    except (BackupError, OSError):
        # Paths, SQL and file contents are intentionally absent from failures.
        print(json.dumps({"ok": False, "error": "Snapshot operation refused; check paths, integrity, manifest and free space"}))
        return 2
    print(json.dumps({"ok": True, "operation": args.operation, "sha256": result["sha256"], "size_bytes": result["size_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
