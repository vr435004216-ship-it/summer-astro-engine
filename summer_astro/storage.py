from pathlib import Path
from datetime import datetime, timezone
import json
import sqlite3
from .contracts import canonical, digest

class ForecastStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as con:
            con.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, recorded_at TEXT NOT NULL,
                as_of TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
                BEGIN SELECT RAISE(ABORT, 'append-only store'); END;
              CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
                BEGIN SELECT RAISE(ABORT, 'append-only store'); END;
            ''')

    def connect(self):
        con=sqlite3.connect(self.path,timeout=15)
        con.row_factory=sqlite3.Row
        return con

    def append(self,record_id,kind,as_of,payload):
        text=canonical(payload);hashed=digest(payload)
        with self.connect() as con:
            con.execute("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)",(
                record_id,kind,datetime.now(timezone.utc).isoformat(),str(as_of),text,hashed))
            row=con.execute("SELECT * FROM records WHERE id=?",(record_id,)).fetchone()
            if row["payload_hash"]!=hashed or row["kind"]!=kind:
                raise ValueError("idempotency conflict: immutable record ID already has different content")
        return record_id

    def get(self,record_id):
        with self.connect() as con:
            row=con.execute("SELECT * FROM records WHERE id=?",(record_id,)).fetchone()
        if row is None: return None
        if digest(json.loads(row["payload"]))!=row["payload_hash"]:
            raise RuntimeError("stored forecast integrity check failed")
        return {"id":row["id"],"kind":row["kind"],"recorded_at":row["recorded_at"],
            "as_of":row["as_of"],"payload":json.loads(row["payload"]),"payload_hash":row["payload_hash"]}

    def counts(self):
        with self.connect() as con:
            return {r["kind"]:r["n"] for r in con.execute("SELECT kind,count(*) AS n FROM records GROUP BY kind")}
