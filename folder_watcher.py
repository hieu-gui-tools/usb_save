"""
Module theo dõi và phát hiện thay đổi trong thư mục lưu trữ (cả thư mục con).
Tự động nhận diện file mới tạo hoặc file bị sửa đổi nội dung.
"""

import os
import sys
import time
import threading
from typing import Dict, Tuple, Optional, Callable, Set

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Các thư mục hoặc tệp tạm thời cần bỏ qua khi theo dõi
EXCLUDED_DIR_NAMES = {
    ".usb_quarantine",
    "$recycle.bin",
    "system volume information",
    "recycler",
    ".git",
    "__pycache__",
}


def should_skip_file(filename: str) -> bool:
    """Bỏ qua các file tạm thời của Microsoft Office / Windows."""
    fname_lower = filename.lower()
    # File tạm do Word / Excel tạo ra khi đang mở (bắt đầu bằng ~$)
    if fname_lower.startswith("~$"):
        return True
    # File tạm .tmp
    if fname_lower.endswith(".tmp"):
        return True
    # File cơ sở dữ liệu sqlite hoặc log nội bộ
    if fname_lower.endswith((".db", ".db-journal", ".db-wal", ".db-shm")):
        return True
    return False


class FolderWatcher:
    """
    Theo dõi thư mục lưu trữ (bao gồm tất cả thư mục con) theo thời gian thực.
    Khi phát hiện file mới hoặc file bị chỉnh sửa, kích hoạt callback on_file_changed.
    """

    def __init__(
        self,
        watch_dir: str,
        on_file_changed: Callable[[str, str], None],
        poll_interval: float = 3.0,
        on_log: Optional[Callable[[str, str], None]] = None,
    ):
        self.watch_dir = os.path.abspath(watch_dir)
        self.on_file_changed = on_file_changed
        self.poll_interval = max(1.0, float(poll_interval))
        self.on_log = on_log or (lambda msg, tag: None)

        self._file_snapshots: Dict[str, Tuple[int, float]] = {}  # {rel_path: (size, mtime)}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def set_watch_dir(self, new_dir: str):
        """Thay đổi thư mục cần theo dõi."""
        with self._lock:
            self.watch_dir = os.path.abspath(new_dir)
            self._file_snapshots.clear()

    def start(self):
        """Bắt đầu tiến trình theo dõi."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="FolderWatcherThread")
        self._thread.start()

    def stop(self):
        """Dừng tiến trình theo dõi."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def scan_now(self):
        """Thực hiện một lần quét ngay lập tức."""
        self._check_folder_changes()

    def _watch_loop(self):
        # Lần quét đầu tiên: Nạp trạng thái ban đầu của tất cả các file
        self._check_folder_changes(is_initial=True)

        while self._running:
            time.sleep(self.poll_interval)
            if not self._running:
                break
            try:
                self._check_folder_changes(is_initial=False)
            except Exception as e:
                pass

    def _check_folder_changes(self, is_initial: bool = False):
        with self._lock:
            target_dir = self.watch_dir

        if not os.path.isdir(target_dir):
            return

        current_files: Dict[str, Tuple[int, float]] = {}

        try:
            for root, dirs, files in os.walk(target_dir):
                # Loại trừ các thư mục không mong muốn
                dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIR_NAMES]

                for fname in files:
                    if should_skip_file(fname):
                        continue

                    abs_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(abs_path, target_dir)

                    try:
                        stat = os.stat(abs_path)
                        current_files[rel_path] = (stat.st_size, stat.st_mtime)
                    except OSError:
                        continue
        except Exception:
            return

        # So sánh với snapshot trước đó
        with self._lock:
            old_snapshots = self._file_snapshots

            for rel_path, (size, mtime) in current_files.items():
                abs_path = os.path.join(target_dir, rel_path)

                if rel_path not in old_snapshots:
                    # File mới xuất hiện
                    if not is_initial:
                        self.on_log(f"🔔 Phát hiện file mới: {rel_path}", "TELEGRAM")
                        self.on_file_changed(abs_path, rel_path)
                    else:
                        # Ở lần khởi động đầu tiên, vẫn chuyển giao file để kiểm tra xem đã upload chưa
                        self.on_file_changed(abs_path, rel_path)
                else:
                    old_size, old_mtime = old_snapshots[rel_path]
                    # Nếu kích thước thay đổi hoặc mtime chênh lệch > 1.0s -> File đã được chỉnh sửa
                    if size != old_size or abs(mtime - old_mtime) > 1.0:
                        self.on_log(f"📝 Phát hiện file đã chỉnh sửa: {rel_path}", "TELEGRAM")
                        self.on_file_changed(abs_path, rel_path)

            # Cập nhật snapshot hiện tại
            self._file_snapshots = current_files
