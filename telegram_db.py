"""
Module quản lý cơ sở dữ liệu SQLite lưu lịch sử upload file lên Telegram.
Ghi nhận đầy đủ thông tin: đường dẫn file, mã băm SHA-256, dung lượng,
thời điểm upload, message_id/file_id từ Telegram, trạng thái và lỗi nếu có.
"""

import os
import sys
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_DB_NAME = "telegram_backup.db"


class TelegramHistoryDB:
    """Quản lý kết nối và thao tác với SQLite database lưu lịch sử upload Telegram."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Lưu file DB cùng thư mục với script
            base_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(base_dir, DEFAULT_DB_NAME)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _connection(self):
        """Context manager đảm bảo commit và luôn close connection để tránh WinError 32."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Khởi tạo bảng và index nếu chưa tồn tại."""
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS upload_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rel_path TEXT NOT NULL,
                        abs_path TEXT NOT NULL,
                        file_hash TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        status TEXT NOT NULL,
                        telegram_message_id INTEGER,
                        telegram_file_id TEXT,
                        retry_count INTEGER DEFAULT 0,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rel_hash ON upload_history(rel_path, file_hash)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_status ON upload_history(status)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_file_hash ON upload_history(file_hash)"
                )

    def is_already_uploaded(self, rel_path: str, file_hash: str) -> bool:
        """
        Kiểm tra xem file này với nội dung mã băm (SHA-256) này đã từng được
        upload thành công lên Telegram hay chưa (tránh upload trùng lặp).
        """
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id FROM upload_history
                    WHERE rel_path = ? AND file_hash = ? AND status = 'SUCCESS'
                    LIMIT 1
                    """,
                    (rel_path, file_hash),
                )
                return cursor.fetchone() is not None

    def record_pending(self, rel_path: str, abs_path: str, file_hash: str, file_size: int, mtime: float) -> int:
        """
        Tạo hoặc cập nhật bản ghi đang chuẩn bị upload (PENDING).
        Trả về ID của bản ghi.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, retry_count FROM upload_history
                    WHERE rel_path = ? AND file_hash = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (rel_path, file_hash),
                )
                row = cursor.fetchone()
                if row:
                    record_id = row["id"]
                    cursor.execute(
                        """
                        UPDATE upload_history
                        SET abs_path = ?, file_size = ?, mtime = ?, status = 'PENDING',
                            error_message = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (abs_path, file_size, mtime, now, record_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO upload_history (
                            rel_path, abs_path, file_hash, file_size, mtime,
                            status, retry_count, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
                        """,
                        (rel_path, abs_path, file_hash, file_size, mtime, now, now),
                    )
                    record_id = cursor.lastrowid
                return record_id

    def mark_success(self, record_id: int, message_id: Optional[int], file_id: Optional[str]):
        """Cập nhật trạng thái upload thành công."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE upload_history
                    SET status = 'SUCCESS',
                        telegram_message_id = ?,
                        telegram_file_id = ?,
                        error_message = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (message_id, file_id, now, record_id),
                )

    def mark_failed(self, record_id: int, error_message: str):
        """Cập nhật trạng thái upload thất bại và tăng biến đếm retry_count."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE upload_history
                    SET status = 'FAILED',
                        retry_count = retry_count + 1,
                        error_message = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (error_message, now, record_id),
                )

    def get_recent_history(self, limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lấy danh sách lịch sử upload gần đây nhất."""
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                if status:
                    cursor.execute(
                        """
                        SELECT * FROM upload_history
                        WHERE status = ?
                        ORDER BY id DESC LIMIT ?
                        """,
                        (status, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT * FROM upload_history
                        ORDER BY id DESC LIMIT ?
                        """,
                        (limit,),
                    )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]

    def get_pending_or_failed_items(self) -> List[Dict[str, Any]]:
        """Lấy tất cả các bản ghi PENDING hoặc FAILED để thực hiện retry."""
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM upload_history
                    WHERE status IN ('PENDING', 'FAILED')
                    ORDER BY id ASC
                    """
                )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]

    def clear_all_history(self):
        """Xóa toàn bộ lịch sử (dùng khi cần dọn dẹp hoặc test)."""
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM upload_history")
