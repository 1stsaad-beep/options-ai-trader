"""Private PostgreSQL custom archives; restore only into a newly created database.

Connection values are read from an environment variable, never from CLI URLs.
Archive checksums detect corruption, not authenticity. A restore executes SQL:
use only trusted project archives and a dedicated, non-superuser CREATEDB role.
No production endpoints, brokers, account reconciliation or workers are started.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

import psycopg
from psycopg import sql


class BackupError(ValueError):
    """A redacted failure without command, URL, SQL or database contents."""


FORMAT = "options-ai-trader-postgresql-custom"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{0,62}\Z")
TARGET = re.compile(r"oat_restore_[a-z0-9_]{1,50}\Z")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}
MAX_ARCHIVE_BYTES = 50 * 1024**3


class Connection:
    """Explicit libpq settings; representation deliberately omits credentials."""

    def __init__(self, host, port, user, password, database, sslmode, sslrootcert=None):
        self.host, self.port, self.user = host, port, user
        self.password, self.database, self.sslmode = password, database, sslmode
        self.sslrootcert = sslrootcert

    def __repr__(self):
        return "<PostgreSQL connection: redacted>"

    @classmethod
    def from_env(cls, name="OAT_POSTGRES_URL", environ=None):
        environment = os.environ if environ is None else environ
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name):
            raise BackupError("Invalid connection environment variable name")
        value = environment.get(name, "")
        try:
            uri = urlsplit(value)
            query = parse_qs(uri.query, strict_parsing=True)
            if (uri.scheme not in {"postgres", "postgresql"} or not uri.hostname
                    or uri.fragment or not uri.username or uri.password is None
                    or any(key not in {"sslmode", "sslrootcert"} for key in query)
                    or any(len(values) != 1 for values in query.values())):
                raise ValueError
            host, port = uri.hostname, uri.port or 5432
            user, password, database = unquote(uri.username), unquote(uri.password), unquote(uri.path[1:])
            if (not re.fullmatch(r"[A-Za-z0-9_.:\-]+", host) or not 1 <= port <= 65535
                    or not NAME.fullmatch(user) or not NAME.fullmatch(database)
                    or not password or any(char in password for char in "\r\n\0")):
                raise ValueError
            sslmode = query.get("sslmode", ["disable" if host in LOCAL_HOSTS else "verify-full"])[0]
            if sslmode not in {"disable", "verify-full"} or (host not in LOCAL_HOSTS and sslmode != "verify-full"):
                raise ValueError
            root = query.get("sslrootcert", [None])[0]
            if root is not None and (not root or any(c in root for c in "\r\n\0")):
                raise ValueError
            return cls(host, port, user, password, database, sslmode, root)
        except (ValueError, TypeError):
            raise BackupError("Connection configuration refused; use an explicit PostgreSQL URL in the named environment variable") from None

    def kwargs(self, database=None):
        values = {"host": self.host, "port": self.port, "user": self.user,
                  "password": self.password, "dbname": database or self.database,
                  "sslmode": self.sslmode, "connect_timeout": 10,
                  "application_name": "options_ai_trader_backup",
                  "options": "-c statement_timeout=30000 -c lock_timeout=10000"}
        if self.sslrootcert:
            values["sslrootcert"] = self.sslrootcert
        return values


def manifest_path(path):
    return Path(str(path) + ".manifest.json")


def _regular_open(path, limit=None):
    """Reject symlinks even if the pathname changes between inspection/open."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        information = os.fstat(descriptor)
        if not stat.S_ISREG(information.st_mode) or (limit is not None and information.st_size > limit):
            os.close(descriptor)
            raise BackupError("Input is not an allowed regular file")
        return os.fdopen(descriptor, "rb")
    except OSError:
        raise BackupError("Input could not be opened safely") from None


def _destination(path):
    path = Path(path)
    if not path.name or not path.parent.is_dir():
        raise BackupError("Create a private destination directory first")
    parent = path.parent.resolve()
    if stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise BackupError("Destination directory must be private (mode 0700)")
    target = parent / path.name
    if any(os.path.lexists(candidate) for candidate in (target, manifest_path(target))):
        raise BackupError("Archive or manifest already exists; nothing is overwritten")
    return target


def _hash(path):
    digest, count = hashlib.sha256(), 0
    with _regular_open(path, MAX_ARCHIVE_BYTES) as source:
        while chunk := source.read(1024 * 1024):
            count += len(chunk)
            if count > MAX_ARCHIVE_BYTES:
                raise BackupError("Archive size limit exceeded")
            digest.update(chunk)
    return digest.hexdigest(), count


def _manifest(snapshot):
    try:
        def unique_pairs(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise BackupError("Duplicate archive manifest key")
                result[key] = item
            return result
        with _regular_open(manifest_path(snapshot), 16384) as stream:
            raw = stream.read(16385)
            if len(raw) > 16384:
                raise BackupError("Oversized archive manifest")
            value = json.loads(raw, object_pairs_hook=unique_pairs)
        required = {"format", "version", "created_utc", "sha256", "size_bytes"}
        if (not isinstance(value, dict) or set(value) != required or value["format"] != FORMAT
                or type(value["version"]) is not int or value["version"] != 1
                or type(value["size_bytes"]) is not int or not 5 <= value["size_bytes"] <= MAX_ARCHIVE_BYTES
                or not isinstance(value["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
                or not isinstance(value["created_utc"], str) or len(value["created_utc"]) > 64):
            raise BackupError("Unsupported or malformed archive manifest")
        created = datetime.fromisoformat(value["created_utc"])
        if created.tzinfo is None:
            raise BackupError("Archive manifest requires a timezone")
        return value
    except (ValueError, UnicodeError, OSError):
        raise BackupError("Archive manifest could not be verified") from None


def _private_copy(snapshot, directory):
    expected = _manifest(snapshot)
    target = Path(directory) / "verified.dump"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    digest, size = hashlib.sha256(), 0
    with os.fdopen(descriptor, "wb") as out, _regular_open(snapshot, MAX_ARCHIVE_BYTES) as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > expected["size_bytes"]:
                raise BackupError("Archive checksum or size mismatch")
            digest.update(chunk)
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    if size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
        raise BackupError("Archive checksum or size mismatch")
    with target.open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise BackupError("Only PostgreSQL custom archives are accepted")
    return target, expected


def _executable(name):
    executable = shutil.which(name)
    if not executable:
        raise BackupError("Matching PostgreSQL client tools must be installed")
    return executable


def _validate_timeout(timeout):
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise BackupError("Invalid operation timeout")


def _run(arguments, *, environment=None, timeout=300):
    """No shell, no inherited stdin, no raw stderr, no credentials in argv."""
    _validate_timeout(timeout)
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=environment, timeout=timeout,
                                check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("PostgreSQL client unavailable or timed out; inspect the isolated target before retrying") from None
    if result.returncode:
        raise BackupError("PostgreSQL client failed; no raw database output is disclosed")


def _offline_environment():
    # Do not forward inherited DB URLs, passwords, PGOPTIONS, service files,
    # dynamic loader variables, provider tokens or unrelated application keys.
    return {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}


@contextmanager
def _credentials(connection, directory, database):
    passfile = Path(directory) / "connection.pgpass"
    escape = lambda value: str(value).replace("\\", "\\\\").replace(":", "\\:")
    descriptor = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(":".join(escape(value) for value in
                            (connection.host, connection.port, database, connection.user, connection.password)) + "\n")
    environment = _offline_environment()
    environment.update(PGPASSFILE=str(passfile), PGSSLMODE=connection.sslmode,
                       PGCONNECT_TIMEOUT="10", PGAPPNAME="options_ai_trader_backup",
                       PGOPTIONS="-c statement_timeout=300000 -c lock_timeout=10000")
    if connection.sslrootcert:
        environment["PGSSLROOTCERT"] = connection.sslrootcert
    try:
        yield environment
    finally:
        passfile.unlink(missing_ok=True)


def _connection_args(connection, database=None):
    return ["--host=" + connection.host, "--port=" + str(connection.port),
            "--username=" + connection.user, "--dbname=" + (database or connection.database), "--no-password"]


def _archive_list(path, *, timeout=30):
    _run([_executable("pg_restore"), "--list", str(path)], environment=_offline_environment(), timeout=timeout)


def _publish(snapshot, target, metadata, directory):
    manifest_temp = Path(directory) / "manifest.json"
    descriptor = os.open(manifest_temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(metadata, file, sort_keys=True, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    with snapshot.open("rb") as file:
        os.fsync(file.fileno())
    published_manifest = False
    try:
        os.link(manifest_temp, manifest_path(target))
        published_manifest = True
        os.link(snapshot, target)
    except FileExistsError:
        if published_manifest:
            try:
                if os.path.samefile(manifest_temp, manifest_path(target)):
                    manifest_path(target).unlink()
            except FileNotFoundError:
                pass
        raise BackupError("Concurrent archive creation refused; existing files preserved") from None
    descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup(connection, destination, *, timeout=300):
    _validate_timeout(timeout)
    target = _destination(destination)
    with tempfile.TemporaryDirectory(prefix=".oat-pg-backup-", dir=target.parent) as directory:
        snapshot = Path(directory) / "snapshot.dump"
        descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        with _credentials(connection, directory, connection.database) as environment:
            _run([_executable("pg_dump"), *_connection_args(connection), "--format=custom", "--no-owner", "--no-acl",
                  "--no-publications", "--no-subscriptions", "--file=" + str(snapshot)],
                 environment=environment, timeout=timeout)
        _archive_list(snapshot)
        with snapshot.open("rb") as source:
            if source.read(5) != b"PGDMP":
                raise BackupError("Client did not produce a custom archive")
        digest, size = _hash(snapshot)
        metadata = {"format": FORMAT, "version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                    "sha256": digest, "size_bytes": size}
        _publish(snapshot, target, metadata, directory)
        return metadata


def verify(snapshot):
    with tempfile.TemporaryDirectory(prefix="oat-pg-verify-") as directory:
        copied, metadata = _private_copy(Path(snapshot), directory)
        _archive_list(copied)
        return metadata


def _connect(connection, database=None, *, autocommit=False):
    try:
        return psycopg.connect(**connection.kwargs(database), autocommit=autocommit)
    except psycopg.Error:
        raise BackupError("PostgreSQL connection failed; credentials and host are redacted") from None


def _create_new_database(connection, database):
    """CREATE DATABASE itself resolves races; no DROP, --clean or overwrite."""
    try:
        with _connect(connection, autocommit=True) as db:
            role = db.execute("SELECT rolsuper, rolcreaterole, rolreplication, rolbypassrls, rolcreatedb "
                              "FROM pg_roles WHERE rolname = current_user").fetchone()
            if role is None or any(role[:4]) or not role[4]:
                raise BackupError("Restore requires a dedicated non-superuser CREATEDB role without elevated role, replication or RLS privileges")
            if db.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone():
                raise BackupError("Restore target already exists; nothing is overwritten")
            db.execute(sql.SQL("CREATE DATABASE {} WITH TEMPLATE template0 ALLOW_CONNECTIONS false").format(sql.Identifier(database)))
            # Keep public users out before the database is ever connectable.
            db.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
            db.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(database)))
    except psycopg.Error:
        raise BackupError("New database creation failed; any database already created is preserved for operator review") from None


def _empty_target(connection, database):
    try:
        with _connect(connection, database) as db:
            if db.execute("SELECT 1 FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid "
                          "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' LIMIT 1").fetchone():
                raise BackupError("New restore target is not empty; restore refused")
    except psycopg.Error:
        raise BackupError("New restore target could not be checked") from None


def restore(connection, snapshot, target_database, *, trusted_archive=False, timeout=300):
    _validate_timeout(timeout)
    if trusted_archive is not True:
        raise BackupError("Restoring SQL requires explicit acknowledgement of a trusted project archive")
    if (not isinstance(target_database, str) or not TARGET.fullmatch(target_database)
            or target_database == connection.database):
        raise BackupError("Use a new database name beginning oat_restore_ with lowercase letters, digits or underscores")
    with tempfile.TemporaryDirectory(prefix="oat-pg-restore-") as directory:
        copied, metadata = _private_copy(Path(snapshot), directory)
        _archive_list(copied)
        _create_new_database(connection, target_database)
        _empty_target(connection, target_database)
        with _credentials(connection, directory, target_database) as environment:
            _run([_executable("pg_restore"), *_connection_args(connection, target_database),
                  "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl",
                  "--no-publications", "--no-subscriptions", "--no-tablespaces", str(copied)],
                 environment=environment, timeout=timeout)
        return {**metadata, "restored_to_new_database": True, "requires_application_reconciliation": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    command = commands.add_parser("backup", help="Create a new archive and checksum manifest")
    command.add_argument("destination", type=Path)
    command.add_argument("--connection-env", default="OAT_POSTGRES_URL")
    command.add_argument("--timeout", type=int, default=300)
    command = commands.add_parser("verify", help="Verify checksum and custom archive directory; no database connection")
    command.add_argument("snapshot", type=Path)
    command = commands.add_parser("restore", help="Restore trusted SQL into a new isolated oat_restore_* database")
    command.add_argument("snapshot", type=Path)
    command.add_argument("target_database")
    command.add_argument("--connection-env", default="OAT_POSTGRES_URL")
    command.add_argument("--trusted-project-archive", action="store_true")
    command.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        if args.operation == "verify":
            result = verify(args.snapshot)
        elif args.operation == "backup":
            result = backup(Connection.from_env(args.connection_env), args.destination, timeout=args.timeout)
        else:
            result = restore(Connection.from_env(args.connection_env), args.snapshot, args.target_database,
                             trusted_archive=args.trusted_project_archive, timeout=args.timeout)
    except (BackupError, OSError, psycopg.Error):
        print(json.dumps({"ok": False, "error": "PostgreSQL archive operation refused; check configuration, trusted source, integrity, privileges and new target. Existing files/databases are preserved."}))
        return 2
    print(json.dumps({"ok": True, "operation": args.operation, "sha256": result["sha256"], "size_bytes": result["size_bytes"],
                      "requires_application_reconciliation": args.operation == "restore"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
