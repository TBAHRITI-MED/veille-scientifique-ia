"""Petit cache clé → JSON sur SQLite, avec date d'expiration par entrée.

Le h-index d'un auteur bouge lentement : inutile de le redemander à chaque recherche.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class JsonCache:
    def __init__(self, path: Path | str):
        self.path = Path(path) if path != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " namespace TEXT, key TEXT, value TEXT, expires_at REAL,"
            " PRIMARY KEY (namespace, key))"
        )
        self._conn.commit()

    def get_many(self, namespace: str, keys: list[str]) -> dict[str, object]:
        """Valeurs encore valides pour les clés demandées (les autres sont absentes du résultat)."""
        found: dict[str, object] = {}
        now = time.time()
        with self._lock:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                rows = self._conn.execute(
                    f"SELECT key, value FROM cache WHERE namespace = ? AND expires_at > ?"
                    f" AND key IN ({','.join('?' * len(chunk))})",
                    [namespace, now, *chunk],
                ).fetchall()
                found.update({k: json.loads(v) for k, v in rows})
        return found

    def set_many(self, namespace: str, items: dict[str, object], ttl_seconds: float) -> None:
        expires = time.time() + ttl_seconds
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO cache (namespace, key, value, expires_at) VALUES (?, ?, ?, ?)",
                [(namespace, k, json.dumps(v, ensure_ascii=False), expires) for k, v in items.items()],
            )
            self._conn.commit()

    def clear(self, namespace: str | None = None) -> None:
        with self._lock:
            if namespace:
                self._conn.execute("DELETE FROM cache WHERE namespace = ?", [namespace])
            else:
                self._conn.execute("DELETE FROM cache")
            self._conn.commit()
