"""
Bộ kiểm thử tự động toàn diện tính năng Sao lưu đám mây Telegram:
1. SQLite Database: Tạo bảng, lưu lịch sử, kiểm tra trùng lặp (SHA-256), trạng thái SUCCESS/FAILED/PENDING.
2. Hash SHA-256 & Tính ổn định của tệp tin (Settle/Debounce check).
3. Telegram Uploader: Gửi tệp, xử lý phản hồi HTTP, thử lại khi gặp lỗi mạng/rate limit, kiểm tra giới hạn 50MB.
4. Folder Watcher: Theo dõi đệ quy thư mục và thư mục con, phát hiện file mới và file sửa đổi, bỏ qua file tạm.
5. Telegram Backup Manager: Điều phối hàng đợi, chống trùng lặp, retry.
"""

import os
import sys
import time
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch, MagicMock
import urllib.error

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from telegram_db import TelegramHistoryDB
from telegram_backup import (
    calculate_file_hash,
    is_file_settled,
    TelegramUploader,
    TelegramBackupManager,
    TELEGRAM_MAX_FILE_SIZE,
)
from folder_watcher import FolderWatcher, should_skip_file


class TestTelegramDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_backup.db")
        self.db = TelegramHistoryDB(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_pending_and_mark_success(self):
        rel_path = "SubFolder/report.docx"
        abs_path = os.path.join(self.temp_dir.name, rel_path)
        file_hash = "abc123hash"
        size = 1024
        mtime = time.time()

        rec_id = self.db.record_pending(rel_path, abs_path, file_hash, size, mtime)
        self.assertGreater(rec_id, 0)

        # Ban đầu trạng thái là PENDING -> is_already_uploaded phải là False
        self.assertFalse(self.db.is_already_uploaded(rel_path, file_hash))

        # Đánh dấu SUCCESS
        self.db.mark_success(rec_id, message_id=999, file_id="tg_file_001")

        # Sau khi SUCCESS -> is_already_uploaded phải là True
        self.assertTrue(self.db.is_already_uploaded(rel_path, file_hash))

        # Nếu file_hash khác -> Chưa được upload
        self.assertFalse(self.db.is_already_uploaded(rel_path, "different_hash"))

    def test_mark_failed_and_retry_count(self):
        rel_path = "sheet.xlsx"
        abs_path = os.path.join(self.temp_dir.name, rel_path)
        file_hash = "hash_sheet"
        rec_id = self.db.record_pending(rel_path, abs_path, file_hash, 2048, time.time())

        self.db.mark_failed(rec_id, "Connection timed out")
        self.assertFalse(self.db.is_already_uploaded(rel_path, file_hash))

        history = self.db.get_recent_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "FAILED")
        self.assertEqual(history[0]["retry_count"], 1)
        self.assertEqual(history[0]["error_message"], "Connection timed out")

        pending_or_failed = self.db.get_pending_or_failed_items()
        self.assertEqual(len(pending_or_failed), 1)

    def test_clear_all_history(self):
        self.db.record_pending("doc.pdf", "C:\\doc.pdf", "hash", 100, time.time())
        self.assertEqual(len(self.db.get_recent_history()), 1)
        self.db.clear_all_history()
        self.assertEqual(len(self.db.get_recent_history()), 0)


class TestFileHashAndSettle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_calculate_file_hash(self):
        fpath1 = os.path.join(self.temp_dir.name, "file1.txt")
        fpath2 = os.path.join(self.temp_dir.name, "file2.txt")

        with open(fpath1, "wb") as f:
            f.write(b"Hello Telegram Backup")
        with open(fpath2, "wb") as f:
            f.write(b"Hello Telegram Backup")

        hash1 = calculate_file_hash(fpath1)
        hash2 = calculate_file_hash(fpath2)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA-256 là 64 ký tự hex

        # Thay đổi nội dung -> mã băm phải khác
        with open(fpath2, "wb") as f:
            f.write(b"Modified content")
        self.assertNotEqual(hash1, calculate_file_hash(fpath2))

    def test_is_file_settled_stable(self):
        fpath = os.path.join(self.temp_dir.name, "stable.docx")
        with open(fpath, "wb") as f:
            f.write(b"Completed file content")

        # File tĩnh đã ghi xong -> Settle phải True
        settled = is_file_settled(fpath, settle_delay=0.1)
        self.assertTrue(settled)


class TestTelegramUploader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sample_file = os.path.join(self.temp_dir.name, "document.pdf")
        with open(self.sample_file, "wb") as f:
            f.write(b"%PDF-1.4 Mock Document Content")

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("urllib.request.urlopen")
    def test_test_connection_success(self, mock_urlopen):
        # Giả lập phản hồi getMe và sendMessage thành công
        resp_me = MagicMock()
        resp_me.read.return_value = b'{"ok": true, "result": {"username": "BackupBot"}}'
        resp_me.__enter__.return_value = resp_me

        resp_send = MagicMock()
        resp_send.read.return_value = b'{"ok": true, "result": {"message_id": 123}}'
        resp_send.__enter__.return_value = resp_send

        mock_urlopen.side_effect = [resp_me, resp_send]

        ok, msg = TelegramUploader.test_connection("12345:TOKEN", "-1001234567")
        self.assertTrue(ok)
        self.assertIn("thành công", msg.lower())

    @patch("urllib.request.urlopen")
    def test_send_document_success(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = b'{"ok": true, "result": {"message_id": 456, "document": {"file_id": "tg_doc_999"}}}'
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        ok, res_data, err = TelegramUploader.send_document(
            bot_token="12345:TOKEN",
            chat_id="-1001234567",
            file_path=self.sample_file,
            caption="Test Caption",
        )
        self.assertTrue(ok)
        self.assertIsNotNone(res_data)
        self.assertEqual(res_data["message_id"], 456)
        self.assertEqual(res_data["document"]["file_id"], "tg_doc_999")

    @patch("urllib.request.urlopen")
    def test_send_document_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection reset by peer")

        ok, res_data, err = TelegramUploader.send_document(
            bot_token="12345:TOKEN",
            chat_id="-1001234567",
            file_path=self.sample_file,
        )
        self.assertFalse(ok)
        self.assertIsNone(res_data)
        self.assertIn("NETWORK_ERROR", err)

    def test_send_document_file_too_large(self):
        with patch("os.path.getsize", return_value=TELEGRAM_MAX_FILE_SIZE + 1024):
            ok, res_data, err = TelegramUploader.send_document(
                bot_token="12345:TOKEN",
                chat_id="-1001234567",
                file_path=self.sample_file,
            )
            self.assertFalse(ok)
            self.assertIn("50MB", err)


class TestFolderWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.watch_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_should_skip_file(self):
        self.assertTrue(should_skip_file("~$Contract.docx"))
        self.assertTrue(should_skip_file("temp_file.tmp"))
        self.assertTrue(should_skip_file("database.db"))
        self.assertFalse(should_skip_file("Contract.docx"))
        self.assertFalse(should_skip_file("Report.pdf"))

    def test_watcher_detects_files_recursively(self):
        changed_files = []

        def on_change(abs_p, rel_p):
            changed_files.append((abs_p, rel_p))

        watcher = FolderWatcher(
            watch_dir=self.watch_dir,
            on_file_changed=on_change,
            poll_interval=0.5,
        )

        # Tạo file ở thư mục con
        sub = os.path.join(self.watch_dir, "MyUSB_E", "Documents")
        os.makedirs(sub, exist_ok=True)
        doc1 = os.path.join(sub, "Financials.xlsx")
        with open(doc1, "wb") as f:
            f.write(b"data 1")

        # Quét lần đầu nạp danh sách
        watcher.scan_now()
        # Ở lần quét đầu, nạp file ban đầu
        self.assertEqual(len(changed_files), 1)
        self.assertIn("Financials.xlsx", changed_files[0][1])

        # Tạo file mới thứ hai
        doc2 = os.path.join(self.watch_dir, "Direct.pdf")
        with open(doc2, "wb") as f:
            f.write(b"data 2")

        watcher.scan_now()
        self.assertEqual(len(changed_files), 2)


class TestTelegramBackupManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "tg_test.db")
        self.manager = TelegramBackupManager(db_path=self.db_path)
        self.manager.configure(
            bot_token="test_token",
            chat_id="test_chat",
            enabled=True,
            settle_delay=0.1,
        )

    def tearDown(self):
        self.manager.stop()
        self.temp_dir.cleanup()

    @patch("telegram_backup.TelegramUploader.send_document")
    def test_manager_deduplication(self, mock_send):
        mock_send.return_value = (True, {"message_id": 101, "document": {"file_id": "f_101"}}, "OK")

        sample_file = os.path.join(self.temp_dir.name, "report.docx")
        with open(sample_file, "wb") as f:
            f.write(b"Initial report content")

        self.manager.start()
        self.manager.enqueue_file(sample_file, "report.docx")

        # Chờ worker xử lý
        time.sleep(1.0)
        mock_send.assert_called_once()

        # Enqueue lại cùng file không đổi nội dung -> Phải bị chặn bởi Deduplication
        mock_send.reset_mock()
        self.manager.enqueue_file(sample_file, "report.docx")
        time.sleep(0.5)
        mock_send.assert_not_called()


if __name__ == "__main__":
    print("Đang chạy kiểm thử tự động Telegram Backup...")
    unittest.main(verbosity=2)
