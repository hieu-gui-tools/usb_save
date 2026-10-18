"""
Module xử lý tải file lên Telegram Group và quản lý hàng đợi sao lưu đám mây.
Bao gồm:
- Tính toán mã băm SHA-256 để chống trùng lặp.
- Kiểm tra tính ổn định của file (chờ copy/ghi hoàn tất).
- Giao tiếp với Telegram Bot API bằng urllib chuẩn (không cần cài thêm thư viện).
- Hàng đợi ngầm (Background Worker) tự động retry khi gặp sự cố mạng.
"""

import os
import sys
import time
import json
import uuid
import hashlib
import threading
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, Callable
from telegram_db import TelegramHistoryDB

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Giới hạn dung lượng tải lên tài liệu tối đa của Telegram Bot API tiêu chuẩn (50MB)
TELEGRAM_MAX_FILE_SIZE = 50 * 1024 * 1024


def calculate_file_hash(file_path: str, block_size: int = 65536) -> str:
    """Tính mã băm SHA-256 của file theo từng block để tiết kiệm bộ nhớ."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def is_file_settled(file_path: str, settle_delay: float = 2.5) -> bool:
    """
    Kiểm tra xem file đã hoàn tất việc copy hoặc ghi chưa:
    1. File phải tồn tại và có thể mở ở chế độ đọc nhị phân (không bị lock bởi tiến trình khác).
    2. Kích thước và thời gian sửa đổi (mtime) không thay đổi sau khoảng thời gian settle_delay.
    """
    if not os.path.isfile(file_path):
        return False

    try:
        stat_initial = os.stat(file_path)
        # Thử mở file đọc 1 byte để kiểm tra file lock
        with open(file_path, "rb") as f:
            f.read(1)
    except (PermissionError, OSError):
        # File đang bị khóa bởi tiến trình khác (đang copy / đang ghi)
        return False

    time.sleep(settle_delay)

    try:
        stat_later = os.stat(file_path)
        with open(file_path, "rb") as f:
            f.read(1)
    except (PermissionError, OSError):
        return False

    # So sánh kích thước và mtime
    return (stat_initial.st_size == stat_later.st_size) and (stat_initial.st_mtime == stat_later.st_mtime)


class TelegramUploader:
    """Xử lý giao tiếp HTTP với Telegram Bot API."""

    @staticmethod
    def test_connection(bot_token: str, chat_id: str) -> Tuple[bool, str]:
        """
        Kiểm tra Bot Token và quyền gửi tin nhắn vào Chat ID chỉ định.
        """
        if not bot_token or not chat_id:
            return False, "Bot Token hoặc Chat ID chưa được nhập."

        clean_token = bot_token.strip()
        clean_chat_id = chat_id.strip()

        # Bước 1: Kiểm tra Bot Token qua getMe
        try:
            url_me = f"https://api.telegram.org/bot{clean_token}/getMe"
            req = urllib.request.Request(url_me, headers={"User-Agent": "USBShield-BackupBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if not res_data.get("ok"):
                    return False, f"Bot Token không hợp lệ: {res_data.get('description', '')}"
                bot_username = res_data.get("result", {}).get("username", "Bot")
        except urllib.error.HTTPError as e:
            return False, f"Lỗi xác thực Bot Token (HTTP {e.code}): {e.reason}"
        except Exception as e:
            return False, f"Lỗi kết nối mạng đến Telegram: {e}"

        # Bước 2: Thử gửi tin nhắn kiểm tra vào Chat ID
        try:
            url_send = f"https://api.telegram.org/bot{clean_token}/sendMessage"
            payload = {
                "chat_id": clean_chat_id,
                "text": f"🔔 [USB Shield & Backup] Kiểm tra kết nối Telegram thành công với bot @{bot_username}!",
            }
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url_send,
                data=data_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "USBShield-BackupBot/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if res_data.get("ok"):
                    return True, f"Kết nối Telegram thành công! Đã gửi tin nhắn xác nhận tới nhóm qua @{bot_username}."
                return False, f"Telegram từ chối: {res_data.get('description', '')}"
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                desc = err_body.get("description", str(e))
            except Exception:
                desc = str(e)
            return False, f"Không thể gửi tin vào Chat ID {clean_chat_id}: {desc}"
        except Exception as e:
            return False, f"Lỗi kết nối khi gửi tin nhắn test: {e}"

    @staticmethod
    def send_document(
        bot_token: str,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        timeout: int = 120,
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Gửi tệp tài liệu lên Telegram Bot API qua phương thức multipart/form-data.
        Trả về (thành_công, dữ_liệu_kết_quả, thông_điệp_lỗi).
        """
        if not os.path.isfile(file_path):
            return False, None, f"Tệp không tồn tại: {file_path}"

        file_size = os.path.getsize(file_path)
        if file_size > TELEGRAM_MAX_FILE_SIZE:
            return False, None, f"Dung lượng vượt quá 50MB ({file_size / (1024*1024):.1f}MB). Telegram Bot API giới hạn tối đa 50MB."

        clean_token = bot_token.strip()
        clean_chat_id = chat_id.strip()
        filename = os.path.basename(file_path)

        url = f"https://api.telegram.org/bot{clean_token}/sendDocument"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"

        # Xây dựng multipart/form-data payload
        body_parts = []

        # Field: chat_id
        body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
        body_parts.append(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body_parts.append(f"{clean_chat_id}\r\n".encode("utf-8"))

        # Field: caption (nếu có)
        if caption:
            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body_parts.append(f"{caption}\r\n".encode("utf-8"))

        # Field: document
        body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
        body_parts.append(
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")

        try:
            with open(file_path, "rb") as f:
                file_content = f.read()
            body_parts.append(file_content)
            body_parts.append(b"\r\n")
            body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))

            payload_data = b"".join(body_parts)

            req = urllib.request.Request(
                url,
                data=payload_data,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(payload_data)),
                    "User-Agent": "USBShield-BackupBot/1.0",
                },
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                res_bytes = response.read()
                res_data = json.loads(res_bytes.decode("utf-8"))
                if res_data.get("ok"):
                    return True, res_data.get("result", {}), "Upload thành công."
                return False, None, res_data.get("description", "Lỗi không xác định từ Telegram")

        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                desc = err_data.get("description", str(e))
                if e.code == 429:
                    retry_after = err_data.get("parameters", {}).get("retry_after", 10)
                    return False, None, f"RATE_LIMIT: Bị giới hạn tốc độ, thử lại sau {retry_after}s ({desc})"
                return False, None, f"HTTP Error {e.code}: {desc}"
            except Exception:
                return False, None, f"HTTP Error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, None, f"NETWORK_ERROR: {e.reason}"
        except Exception as e:
            return False, None, f"ERROR: {e}"


class TelegramBackupManager:
    """
    Trình quản lý sao lưu lên Telegram Group:
    - Xử lý hàng đợi upload bất đồng bộ.
    - Kiểm tra tính ổn định của file (debounce/settle).
    - Chống upload trùng lặp bằng SQLite + SHA-256.
    - Tự động retry khi gặp lỗi mạng.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
    ):
        self.db = TelegramHistoryDB(db_path=db_path)
        self.on_log = on_log or (lambda msg, tag: None)

        self._queue = []
        self._queue_lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._wake_event = threading.Event()

        # Cấu hình runtime
        self.bot_token = ""
        self.chat_id = ""
        self.enabled = False
        self.settle_delay = 2.5

    def configure(self, bot_token: str, chat_id: str, enabled: bool, settle_delay: float = 2.5):
        """Cập nhật thiết lập Telegram."""
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = enabled
        self.settle_delay = max(0.05, float(settle_delay))


    def start(self):
        """Bắt đầu tiến trình upload ngầm."""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="TelegramBackupWorker")
        self._worker_thread.start()

    def stop(self):
        """Dừng tiến trình ngầm an toàn."""
        self._running = False
        self._wake_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def enqueue_file(self, abs_path: str, rel_path: str):
        """Đưa file vào hàng đợi kiểm tra và upload."""
        if not self.enabled or not self.bot_token or not self.chat_id:
            return

        with self._queue_lock:
            # Tránh thêm trùng cùng 1 file đang chờ trong queue
            for item in self._queue:
                if item["abs_path"] == abs_path:
                    return
            self._queue.append({"abs_path": abs_path, "rel_path": rel_path, "added_at": time.time()})
        self._wake_event.set()

    def retry_failed_items(self):
        """Đưa tất cả các file từng bị lỗi (FAILED) trong SQLite vào lại hàng đợi."""
        failed_items = self.db.get_pending_or_failed_items()
        count = 0
        with self._queue_lock:
            for item in failed_items:
                abs_p = item["abs_path"]
                rel_p = item["rel_path"]
                if os.path.exists(abs_p) and not any(q["abs_path"] == abs_p for q in self._queue):
                    self._queue.append({"abs_path": abs_p, "rel_path": rel_p, "added_at": time.time()})
                    count += 1
        if count > 0:
            self.on_log(f"🔄 Đã đưa {count} file lỗi/chờ vào hàng đợi thử lại upload Telegram.", "TELEGRAM")
            self._wake_event.set()

    def _worker_loop(self):
        """Vòng lặp tiến trình worker xử lý upload và retry."""
        retry_delay = 5.0
        while self._running:
            item = None
            with self._queue_lock:
                if self._queue:
                    item = self._queue.pop(0)

            if not item:
                # Không có việc, chờ tín hiệu hoặc thức dậy sau 10s kiểm tra
                self._wake_event.wait(timeout=10.0)
                self._wake_event.clear()
                continue

            abs_path = item["abs_path"]
            rel_path = item["rel_path"]

            # Kiểm tra xem file còn tồn tại không
            if not os.path.isfile(abs_path):
                continue

            # 1. Chờ hoàn tất việc copy/ghi (Debounce/Settle check)
            if not is_file_settled(abs_path, settle_delay=self.settle_delay):
                # File vẫn đang được ghi hoặc bị lock -> đẩy lại cuối hàng đợi sau một khoảng thời gian
                time.sleep(1.0)
                with self._queue_lock:
                    self._queue.append(item)
                continue

            try:
                file_size = os.path.getsize(abs_path)
                mtime = os.path.getmtime(abs_path)
                file_hash = calculate_file_hash(abs_path)
            except Exception as e:
                # File có thể bị xóa hoặc lỗi đọc
                continue

            # 2. Kiểm tra chống trùng lặp (Deduplication)
            if self.db.is_already_uploaded(rel_path, file_hash):
                # File này với mã băm này đã tải lên thành công rồi -> Bỏ qua
                continue

            # Ghi nhận trạng thái PENDING trong database
            record_id = self.db.record_pending(
                rel_path=rel_path,
                abs_path=abs_path,
                file_hash=file_hash,
                file_size=file_size,
                mtime=mtime,
            )

            filename = os.path.basename(abs_path)
            size_mb = file_size / (1024 * 1024)
            size_str = f"{size_mb:.2f} MB" if size_mb >= 1.0 else f"{file_size / 1024:.1f} KB"
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")

            caption = (
                f"📁 [USB Backup] {rel_path}\n"
                f"📏 Dung lượng: {size_str}\n"
                f"🕒 Thời gian: {timestamp_str}\n"
                f"🔑 SHA-256: {file_hash[:12]}..."
            )

            self.on_log(f"☁️ Đang upload lên Telegram: {filename} ({size_str})...", "TELEGRAM")

            # 3. Tiến hành upload
            success, result_data, error_msg = TelegramUploader.send_document(
                bot_token=self.bot_token,
                chat_id=self.chat_id,
                file_path=abs_path,
                caption=caption,
            )

            if success and result_data:
                msg_id = result_data.get("message_id")
                doc = result_data.get("document", {})
                file_id = doc.get("file_id")
                self.db.mark_success(record_id, msg_id, file_id)
                self.on_log(f"✅ Đã upload thành công lên Telegram: {filename} (ID: {msg_id})", "TELEGRAM_SUCCESS")
                retry_delay = 5.0  # Reset retry delay khi upload thành công
            else:
                self.db.mark_failed(record_id, error_msg)
                self.on_log(f"⚠️ Upload thất bại ({filename}): {error_msg}", "TELEGRAM_WARN")

                # Nếu là lỗi mạng hoặc rate limit, tự động đưa lại vào hàng đợi để retry
                if "NETWORK_ERROR" in error_msg or "RATE_LIMIT" in error_msg or "HTTP Error 5" in error_msg:
                    self.on_log(f"⏳ Tự động lên lịch thử lại sau {retry_delay:.0f}s do sự cố kết nối...", "TELEGRAM")
                    time.sleep(retry_delay)
                    # Tăng dần thời gian chờ thử lại (exponential backoff tối đa 60s)
                    retry_delay = min(60.0, retry_delay * 1.5)
                    with self._queue_lock:
                        self._queue.append(item)
                else:
                    time.sleep(1.0)
