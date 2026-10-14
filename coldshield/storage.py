"""Atomic lab snapshots and durable, editable SQLite audit events."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import contextmanager
from .config import utcnow


class AuditError(RuntimeError):
    pass


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
            name = file.name
            json.dump(data, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
        name = None
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if name is not None:
            os.unlink(name)


class AuditStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                request_id TEXT NOT NULL, phase TEXT NOT NULL, decision TEXT NOT NULL,
                reason TEXT NOT NULL, peer TEXT, transaction_id INTEGER,
                unit_id INTEGER, function INTEGER, register INTEGER, value INTEGER,
                policy_hash TEXT, details TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS events_request ON events(request_id)")
            db.execute("CREATE TABLE IF NOT EXISTS defrost_starts (register INTEGER PRIMARY KEY, started REAL NOT NULL)")

    @contextmanager
    def connect(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=1)
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        except (OSError, sqlite3.Error) as exc:
            raise AuditError(str(exc)) from exc
        finally:
            if db is not None:
                db.close()

    def record(self, request_id, phase, decision, reason, **fields):
        names = ("peer", "transaction_id", "unit_id", "function", "register", "value", "policy_hash")
        try:
            with self.connect() as db:
                db.execute("""INSERT INTO events(timestamp,request_id,phase,decision,reason,
                    peer,transaction_id,unit_id,function,register,value,policy_hash,details)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (utcnow().isoformat(), request_id, phase, decision, reason,
                     *(fields.get(name) for name in names), json.dumps(fields.get("details", {}))))
        except (OSError, sqlite3.Error) as exc:
            raise AuditError(str(exc)) from exc

    def recent_start(self, now, cooldown=120):
        try:
            with self.connect() as db:
                # Future timestamps block after backwards wall-clock changes too.
                return db.execute("SELECT 1 FROM defrost_starts WHERE started > ? LIMIT 1",
                                  (now - cooldown,)).fetchone() is not None
        except sqlite3.Error as exc:
            raise AuditError(str(exc)) from exc

    def reserve_start(self, register, now):
        try:
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO defrost_starts VALUES (?,?)", (register, now))
        except sqlite3.Error as exc:
            raise AuditError(str(exc)) from exc


def read_events(path, limit=200):
    """Read only; a dashboard must never create or repair a missing audit DB."""
    path = Path(path).resolve()
    if not path.exists():
        return []
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        db.close()
