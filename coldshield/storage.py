"""Atomic lab snapshots and bounded, durable SQLite audit events."""
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import contextmanager
from .config import utcnow


class AuditError(RuntimeError):
    pass


class AtomicPublicationError(OSError):
    """A write failed; published distinguishes visibility from durable success."""
    def __init__(self, message, *, published=False):
        super().__init__(message)
        self.published = published
        self.durability_uncertain = published


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, data):
    path = Path(path)
    name = None
    published = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
            name = file.name
            json.dump(data, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
        published = True
        name = None
        fsync_directory(path.parent)
    except (OSError, ValueError, TypeError) as exc:
        raise AtomicPublicationError(str(exc), published=published) from exc
    finally:
        if name is not None:
            try:
                os.unlink(name)
            except OSError:
                pass


AGGREGATE_REASONS = frozenset(("FUNCTION_NOT_ALLOWED", "REGISTER_NOT_ALLOWED", "UNIT_NOT_ALLOWED",
                              "INVALID_PDU", "INVALID_FRAME", "MAINTENANCE_CLOSED"))
EVENT_FIELDS = ("peer", "transaction_id", "unit_id", "function", "register", "value", "policy_hash")


class AuditStore:
    def __init__(self, path, *, max_events=4096, max_bytes=8 * 1024 * 1024,
                 denial_details_limit=256, busy_timeout=.25, max_record_bytes=16384):
        for name, value in (("max_events", max_events), ("max_bytes", max_bytes),
                            ("denial_details_limit", denial_details_limit),
                            ("max_record_bytes", max_record_bytes)):
            if type(value) is not int or value < (0 if name == "denial_details_limit" else 1):
                raise ValueError(f"Invalid {name}")
        if not isinstance(busy_timeout, (int, float)) or not 0 < busy_timeout <= 1:
            raise ValueError("Audit lock timeout must be 0..1 seconds")
        self.path = Path(path)
        self.max_events, self.max_bytes = max_events, max_bytes
        self.denial_details_limit = denial_details_limit
        self.busy_timeout, self.max_record_bytes = busy_timeout, max_record_bytes
        existed = self.path.exists()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AuditError(str(exc)) from exc
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if existed:
                self._validate_existing(db)
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                request_id TEXT NOT NULL, phase TEXT NOT NULL, decision TEXT NOT NULL,
                reason TEXT NOT NULL, peer TEXT, transaction_id INTEGER,
                unit_id INTEGER, function INTEGER, register INTEGER, value INTEGER,
                policy_hash TEXT, details TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS events_request ON events(request_id)")
            db.execute("CREATE TABLE IF NOT EXISTS defrost_starts (register INTEGER PRIMARY KEY, started REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS event_reservations (request_id TEXT PRIMARY KEY, remaining INTEGER NOT NULL CHECK(remaining > 0))")
            db.execute("""CREATE TABLE IF NOT EXISTS denial_summaries (
                reason TEXT PRIMARY KEY, count INTEGER NOT NULL, first_timestamp TEXT NOT NULL,
                last_timestamp TEXT NOT NULL, first_request_id TEXT NOT NULL,
                last_request_id TEXT NOT NULL, sample TEXT NOT NULL)""")
            if self._occupied(db) > self.max_events:
                raise AuditError("Existing audit exceeds event budget")
            db.execute("PRAGMA user_version=3")

    @staticmethod
    def _validate_existing(db):
        # Only the known v0.2 schema may migrate. Missing critical state is an
        # invalid store, never an instruction to recreate an empty interlock.
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise AuditError("Audit integrity check failed")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        core = {"events", "defrost_starts"}
        additional = {"event_reservations", "denial_summaries"}
        if not core <= tables or version not in (0, 3):
            raise AuditError("Invalid existing audit schema or version")
        if version == 0 and additional & tables or version == 3 and not additional <= tables:
            raise AuditError("Incomplete existing audit schema")
        expected = {
            "events": [("id", "INTEGER"), ("timestamp", "TEXT"), ("request_id", "TEXT"),
                       ("phase", "TEXT"), ("decision", "TEXT"), ("reason", "TEXT"),
                       ("peer", "TEXT"), ("transaction_id", "INTEGER"), ("unit_id", "INTEGER"),
                       ("function", "INTEGER"), ("register", "INTEGER"), ("value", "INTEGER"),
                       ("policy_hash", "TEXT"), ("details", "TEXT")],
            "defrost_starts": [("register", "INTEGER"), ("started", "REAL")],
            "event_reservations": [("request_id", "TEXT"), ("remaining", "INTEGER")],
            "denial_summaries": [("reason", "TEXT"), ("count", "INTEGER"),
                                ("first_timestamp", "TEXT"), ("last_timestamp", "TEXT"),
                                ("first_request_id", "TEXT"), ("last_request_id", "TEXT"), ("sample", "TEXT")],
        }
        for table in core | (additional if version == 3 else set()):
            columns = db.execute(f"PRAGMA table_info({table})").fetchall()
            if [(row[1], row[2]) for row in columns] != expected[table] or columns[0][5] != 1:
                raise AuditError("Invalid existing audit columns or primary key")
        for register, started in db.execute("SELECT register,started FROM defrost_starts"):
            if type(register) is not int or register not in (10, 11, 12) or type(started) not in (int, float) or not math.isfinite(started):
                raise AuditError("Invalid persistent defrost state")
        if version == 3:
            for request, remaining in db.execute("SELECT request_id,remaining FROM event_reservations"):
                if not isinstance(request, str) or not request or type(remaining) is not int or remaining <= 0:
                    raise AuditError("Invalid pending audit reservation")
            for reason, count in db.execute("SELECT reason,count FROM denial_summaries"):
                if reason not in AGGREGATE_REASONS or type(count) is not int or count <= 0:
                    raise AuditError("Invalid denial summary")

    @contextmanager
    def connect(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=self.busy_timeout)
            db.execute(f"PRAGMA busy_timeout={int(self.busy_timeout * 1000)}")
            db.execute("PRAGMA synchronous=FULL")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            pages = self.max_bytes // page_size
            if pages < 1 or db.execute("PRAGMA page_count").fetchone()[0] > pages:
                raise AuditError("Audit exceeds byte budget")
            db.execute(f"PRAGMA max_page_count={pages}")
            with db:
                yield db
        except (OSError, sqlite3.Error) as exc:
            raise AuditError(str(exc)) from exc
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _occupied(db):
        return db.execute("SELECT (SELECT count(*) FROM events) + COALESCE((SELECT sum(remaining) FROM event_reservations),0)").fetchone()[0]

    def _json(self, data):
        try:
            encoded = json.dumps(data, allow_nan=False, separators=(",", ":"))
        except (ValueError, TypeError, RecursionError) as exc:
            raise AuditError("Invalid audit fields") from exc
        if len(encoded.encode("utf-8")) > self.max_record_bytes:
            raise AuditError("Audit record exceeds detail byte budget")
        return encoded

    def reserve_events(self, request_id, count=2):
        if type(count) is not int or not 1 <= count <= self.max_events:
            raise AuditError("Invalid event reservation")
        if not isinstance(request_id, str) or not request_id:
            raise AuditError("Invalid reservation request identity")
        self._json({"request_id": request_id})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM event_reservations WHERE request_id=?", (request_id,)).fetchone():
                raise AuditError("Request already has an event reservation")
            if self._occupied(db) + count > self.max_events:
                raise AuditError("Audit event budget exhausted")
            db.execute("INSERT INTO event_reservations VALUES (?,?)", (request_id, count))

    def release_events(self, request_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM event_reservations WHERE request_id=?", (request_id,))

    def record(self, request_id, phase, decision, reason, **fields):
        for value in (request_id, phase, decision, reason):
            if not isinstance(value, str) or not value:
                raise AuditError("Invalid audit identity or classification")
        for name in ("transaction_id", "unit_id", "function", "register", "value"):
            value = fields.get(name)
            if value is not None and (type(value) is not int or not -(2**63) <= value < 2**63):
                raise AuditError(f"Invalid audit integer field: {name}")
        for name in ("peer", "policy_hash"):
            if fields.get(name) is not None and not isinstance(fields[name], str):
                raise AuditError(f"Invalid audit text field: {name}")
        stamp = utcnow().isoformat()
        sample = {name: fields.get(name) for name in EVENT_FIELDS}
        sample["details"] = fields.get("details", {})
        self._json({"request_id": request_id, "phase": phase, "decision": decision,
                    "reason": reason, **sample})
        details = self._json(sample["details"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            aggregate = phase == "decision" and decision == "BLOCKED" and reason in AGGREGATE_REASONS
            if aggregate:
                placeholders = ",".join("?" for _ in AGGREGATE_REASONS)
                individual = db.execute(f"SELECT count(*) FROM events WHERE phase='decision' AND decision='BLOCKED' AND reason IN ({placeholders})", tuple(AGGREGATE_REASONS)).fetchone()[0]
                if individual >= self.denial_details_limit:
                    prior = db.execute("SELECT count, first_timestamp, first_request_id FROM denial_summaries WHERE reason=?", (reason,)).fetchone()
                    count = prior[0] + 1 if prior else 1
                    first_stamp, first_id = (prior[1], prior[2]) if prior else (stamp, request_id)
                    # Counter overflow and summary growth fail explicitly, without truncation.
                    if count > 9223372036854775807:
                        raise AuditError("Denial counter exhausted")
                    encoded = self._json(sample)
                    self._json({"count": count, "first_timestamp": first_stamp,
                                "last_timestamp": stamp, "first_request_id": first_id,
                                "last_request_id": request_id, "sample": sample})
                    db.execute("INSERT OR REPLACE INTO denial_summaries VALUES (?,?,?,?,?,?,?)",
                               (reason, count, first_stamp, stamp, first_id, request_id, encoded))
                    return
            reservation = db.execute("SELECT remaining FROM event_reservations WHERE request_id=?", (request_id,)).fetchone()
            if reservation:
                if reservation[0] == 1:
                    db.execute("DELETE FROM event_reservations WHERE request_id=?", (request_id,))
                else:
                    db.execute("UPDATE event_reservations SET remaining=remaining-1 WHERE request_id=?", (request_id,))
            elif self._occupied(db) >= self.max_events:
                raise AuditError("Audit event budget exhausted")
            db.execute("""INSERT INTO events(timestamp,request_id,phase,decision,reason,
                peer,transaction_id,unit_id,function,register,value,policy_hash,details)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (stamp, request_id, phase, decision, reason,
                 *(fields.get(name) for name in EVENT_FIELDS), details))

    def recent_start(self, now, cooldown=120):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM defrost_starts WHERE started > ? LIMIT 1", (now - cooldown,)).fetchone() is not None

    def reserve_start(self, register, now):
        if type(register) is not int or register not in (10, 11, 12):
            raise AuditError("Invalid defrost reservation register")
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            raise AuditError("Invalid defrost reservation timestamp")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO defrost_starts VALUES (?,?)", (register, now))

    def export(self, path):
        """A coherent local snapshot, including summaries and unresolved reservations."""
        with self.connect() as db:
            db.execute("BEGIN")
            db.row_factory = sqlite3.Row
            data = {"schema_version": 1, "exported_at": utcnow().isoformat()}
            for table, order in (("events", "id"), ("denial_summaries", "reason"),
                                 ("event_reservations", "request_id"), ("defrost_starts", "register")):
                data[table] = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]
        atomic_json(path, data)
        return data


def read_events(path, limit=200):
    """Read only; a dashboard must never create or repair a missing audit DB."""
    path = Path(path).resolve()
    if not path.exists():
        return []
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.25)
    try:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        db.close()
