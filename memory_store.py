from collections import deque
import os
import sqlite3
import threading
from typing import Deque, Dict, Optional


class MemoryStore:
    """Quản lý ngữ cảnh ngắn hạn (RAM) và dài hạn (SQLite) cô lập theo user_id."""

    def __init__(self, db_path: Optional[str] = None, short_limit: int = 8):
        if db_path is None:
            data_dir = os.getenv("DATA_DIR") or "data"
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "bot_memory.db")
        else:
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.db_path = db_path
        self.short_limit = max(2, int(short_limit))
        self._lock = threading.RLock()
        self._short_term: Dict[str, Deque[str]] = {}
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    context TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_user ON long_term_memory (user_id, id)"
            )
            self._conn.commit()

    def get_context(self, user_id: str) -> str:
        uid = str(user_id)
        with self._lock:
            short_deque = self._short_term.setdefault(uid, deque(maxlen=self.short_limit))
            short_ctx = "\n".join(short_deque)
            row = self._conn.execute(
                "SELECT context FROM long_term_memory WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (uid,),
            ).fetchone()
            long_ctx = row[0] if row else ""

        if long_ctx and short_ctx:
            return f"{long_ctx}\n\n{short_ctx}"
        return long_ctx or short_ctx

    def update(self, user_id: str, user_message: str, bot_response: str) -> None:
        uid = str(user_id)
        with self._lock:
            short_deque = self._short_term.setdefault(uid, deque(maxlen=self.short_limit))
            short_deque.append(f"Người dùng: {user_message}")
            short_deque.append(f"Trợ lý AI: {bot_response}")
            merged = "\n".join(short_deque)
            self._conn.execute(
                "INSERT INTO long_term_memory (user_id, context) VALUES (?, ?)",
                (uid, merged),
            )
            self._conn.commit()

    def clear_short(self, user_id: str) -> bool:
        uid = str(user_id)
        with self._lock:
            if uid in self._short_term:
                self._short_term[uid].clear()
                return True
            return False

    def clear_all(self, user_id: str) -> None:
        uid = str(user_id)
        with self._lock:
            self._short_term.pop(uid, None)
            self._conn.execute("DELETE FROM long_term_memory WHERE user_id = ?", (uid,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
