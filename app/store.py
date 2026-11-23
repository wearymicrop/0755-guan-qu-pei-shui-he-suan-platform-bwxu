import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.errors import InputError
from app.manifest import canonical


class Archive:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("""CREATE TABLE IF NOT EXISTS runs (
            digest TEXT PRIMARY KEY, payload TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS idempotency (
            key TEXT PRIMARY KEY, digest TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS confirmations (
            run_id TEXT NOT NULL, outlet TEXT NOT NULL, amount_l INTEGER NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY (run_id, outlet)
        )""")
        return connection

    def find(self, digest):
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT payload FROM runs WHERE digest = ?", (digest,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, digest):
        result = self.find(digest)
        if result is None:
            raise InputError("RUN_NOT_FOUND", "找不到该归档", 404)
        return result

    def save(self, record):
        with closing(self.connect()) as connection, connection:
            inserted = connection.execute(
                "INSERT INTO runs VALUES (?, ?) ON CONFLICT(digest) DO NOTHING",
                (record["id"], canonical(record)),
            ).rowcount
            payload = connection.execute("SELECT payload FROM runs WHERE digest = ?", (record["id"],)).fetchone()[0]
        return json.loads(payload), not inserted

    def resolve_idempotency(self, key):
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT digest FROM idempotency WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def bind_idempotency(self, key, digest):
        with closing(self.connect()) as connection, connection:
            connection.execute(
                "INSERT INTO idempotency VALUES (?, ?) ON CONFLICT(key) DO NOTHING", (key, digest)
            )

    def confirm(self, run_id, outlet, amount_l, payload):
        with closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO confirmations VALUES (?, ?, ?, ?) ON CONFLICT(run_id, outlet) DO NOTHING",
                (run_id, outlet, amount_l, canonical(payload)),
            )
            row = connection.execute(
                "SELECT payload FROM confirmations WHERE run_id = ? AND outlet = ?", (run_id, outlet)
            ).fetchone()[0]
        return json.loads(row), cursor.rowcount == 1

    def confirmations(self, run_id):
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM confirmations WHERE run_id = ? ORDER BY outlet", (run_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
