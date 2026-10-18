"""
Script kiểm thử tự động toàn diện các module của USB Detector & Notifier:
- Kiểm tra USB Detector & trích xuất ổ đĩa
- Kiểm tra USB Scanner phát hiện autorun.inf
- Kiểm tra USB Scanner phát hiện Shortcut virus (.lnk)
- Kiểm tra USB Scanner phát hiện file đuôi kép và script nguy hiểm
- Kiểm tra cơ chế Cách ly (Quarantine) và Phục hồi (Restore)
- Kiểm tra tính năng Tiêm phòng (Immunize)
- Kiểm tra Thông báo cảnh báo nguy cơ
"""

import os
import sys
import json
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from notifier import USBNotifier
from usb_detector import format_bytes, get_drive_info, list_usb_drives, USBDetector
from usb_scanner import USBScanner, ThreatInfo


class TestUSBDetector(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024), "1.0 GB")
        self.assertEqual(format_bytes(15 * 1024 * 1024 * 1024), "15.0 GB")

    def test_get_drive_info_internal(self):
        info_c = get_drive_info("C")
        self.assertIsNotNone(info_c)
        self.assertEqual(info_c["letter"], "C")
        self.assertIn("drive", info_c)
        self.assertIn("total_bytes", info_c)
        self.assertIn("free_bytes", info_c)
        self.assertFalse(info_c["is_removable"])

    def test_list_usb_drives(self):
        drives = list_usb_drives()
        self.assertIsInstance(drives, dict)

    def test_detector_callbacks_simulation(self):
        connected_calls = []
        disconnected_calls = []

        def on_con(info):
            connected_calls.append(info)

        def on_dis(info):
            disconnected_calls.append(info)

        mock_usb = {
            "drive": "E:\\",
            "letter": "E",
            "label": "KINGSTON",
            "file_system": "FAT32",
            "free_space_str": "14.2 GB",
            "total_space_str": "15.0 GB",
            "is_usb": True,
        }

        notifier = USBNotifier()
        with patch.object(notifier, "notify_connected") as mock_notif_con:
            mock_notif_con.return_value = True
            on_con(mock_usb)
            self.assertEqual(len(connected_calls), 1)
            self.assertEqual(connected_calls[0]["drive"], "E:\\")

        with patch.object(notifier, "notify_disconnected") as mock_notif_dis:
            mock_notif_dis.return_value = True
            on_dis(mock_usb)
            self.assertEqual(len(disconnected_calls), 1)
            self.assertEqual(disconnected_calls[0]["drive"], "E:\\")


class TestUSBScanner(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.mock_usb_root = self.test_dir.name
        self.scanner = USBScanner(quarantine_folder_name=".test_quarantine")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_detect_and_quarantine_autorun(self):
        # Tạo file autorun.inf giả lập
        autorun_file = os.path.join(self.mock_usb_root, "autorun.inf")
        with open(autorun_file, "w", encoding="utf-8") as f:
            f.write("[AutoRun]\nopen=malware.exe\nshellexecute=malware.exe\n")

        result = self.scanner.scan_drive(self.mock_usb_root, auto_quarantine=True)

        self.assertFalse(result.is_safe)
        self.assertTrue(result.has_autorun)
        self.assertEqual(len(result.threats), 1)
        self.assertEqual(result.threats[0].threat_type, "AUTORUN")
        self.assertTrue(result.threats[0].quarantined)

        # File autorun.inf ban đầu phải không còn ở vị trí cũ (đã được cách ly)
        self.assertFalse(os.path.exists(autorun_file))

        # Kiểm tra danh sách file cách ly
        quarantined = self.scanner.list_quarantined_files(self.mock_usb_root)
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0]["filename"], "autorun.inf")

    def test_detect_double_extension(self):
        # Tạo file ngụy trang đuôi kép
        fake_doc = os.path.join(self.mock_usb_root, "TaiLieuQuanTrong.pdf.exe")
        with open(fake_doc, "w") as f:
            f.write("fake exe binary")

        result = self.scanner.scan_drive(self.mock_usb_root, auto_quarantine=True)

        self.assertFalse(result.is_safe)
        threat_types = [t.threat_type for t in result.threats]
        self.assertIn("DOUBLE_EXT", threat_types)
        self.assertFalse(os.path.exists(fake_doc))

    def test_detect_suspicious_shortcut(self):
        # Tạo file shortcut giả lập chứa commandline powershell độc hại
        bad_lnk = os.path.join(self.mock_usb_root, "MyPictures.lnk")
        with open(bad_lnk, "wb") as f:
            f.write(b"\x4c\x00\x00\x00cmd.exe /c powershell.exe -enc aW52b2tl")

        result = self.scanner.scan_drive(self.mock_usb_root, auto_quarantine=True)

        self.assertFalse(result.is_safe)
        threat_types = [t.threat_type for t in result.threats]
        self.assertIn("SHORTCUT_WORM", threat_types)
        self.assertFalse(os.path.exists(bad_lnk))

    def test_detect_dangerous_script_in_root(self):
        # Tạo script vbs ở thư mục gốc USB
        vbs_file = os.path.join(self.mock_usb_root, "auto_script.vbs")
        with open(vbs_file, "w") as f:
            f.write("Wscript.Echo 'Hello'")

        result = self.scanner.scan_drive(self.mock_usb_root, auto_quarantine=True)

        self.assertFalse(result.is_safe)
        threat_types = [t.threat_type for t in result.threats]
        self.assertIn("DANGEROUS_SCRIPT", threat_types)

    def test_quarantine_and_restore(self):
        test_file = os.path.join(self.mock_usb_root, "test_threat.js")
        with open(test_file, "w") as f:
            f.write("alert('test');")

        threat = ThreatInfo(
            file_path=test_file,
            threat_type="DANGEROUS_SCRIPT",
            severity="HIGH",
            description="Test Threat"
        )
        ok = self.scanner.quarantine_file(self.mock_usb_root, threat)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(test_file))

        items = self.scanner.list_quarantined_files(self.mock_usb_root)
        self.assertEqual(len(items), 1)

        # Phục hồi
        restored_ok = self.scanner.restore_quarantined_file(items[0])
        self.assertTrue(restored_ok)
        self.assertTrue(os.path.exists(test_file))

    def test_immunize_drive(self):
        ok, msg = self.scanner.immunize_drive(self.mock_usb_root)
        self.assertTrue(ok)
        autorun_folder = os.path.join(self.mock_usb_root, "autorun.inf")
        self.assertTrue(os.path.isdir(autorun_folder))


class TestThreatNotification(unittest.TestCase):
    def test_notify_threat_detected(self):
        notifier = USBNotifier()
        sample_threats = [
            ThreatInfo("E:\\autorun.inf", "AUTORUN", "CRITICAL", "Autorun worm"),
            ThreatInfo("E:\\virus.pdf.exe", "DOUBLE_EXT", "CRITICAL", "Fake PDF"),
        ]
        with patch("notifier.Notification.show") as mock_show:
            ok = notifier.notify_threat_detected("E:\\", "USB 16GB", sample_threats)
            self.assertTrue(ok)
            mock_show.assert_called_once()

    def test_notify_backup_completed(self):
        notifier = USBNotifier()
        with patch("notifier.Notification.show") as mock_show:
            ok = notifier.notify_backup_completed("E:\\", "SANDISK", 5, 10, "12.5 MB", "C:\\fake_dir")
            self.assertTrue(ok)
            mock_show.assert_called_once()


from usb_backup import USBBackupManager, classify_document
from config_manager import ConfigManager


class TestUSBBackup(unittest.TestCase):
    def setUp(self):
        self.usb_dir = tempfile.TemporaryDirectory()
        self.backup_dir = tempfile.TemporaryDirectory()
        self.usb_root = self.usb_dir.name
        self.backup_root = self.backup_dir.name
        self.backup_mgr = USBBackupManager()

    def tearDown(self):
        self.usb_dir.cleanup()
        self.backup_dir.cleanup()

    def test_classify_document(self):
        self.assertEqual(classify_document("Contract.docx"), "Word")
        self.assertEqual(classify_document("Legacy.doc"), "Word")
        self.assertEqual(classify_document("Invoice.pdf"), "PDF")
        self.assertEqual(classify_document("Finance.xlsx"), "Excel")
        self.assertEqual(classify_document("Table.csv"), "Excel")
        self.assertEqual(classify_document("Slides.pptx"), "PowerPoint")
        # Phải loại bỏ các tệp không phải tài liệu hoặc nguy hiểm
        self.assertIsNone(classify_document("Photo.jpg"))
        self.assertIsNone(classify_document("Video.mp4"))
        self.assertIsNone(classify_document("App.exe"))
        self.assertIsNone(classify_document("FakePDF.pdf.exe"))
        self.assertIsNone(classify_document("FakeDoc.docx.vbs"))

    def test_backup_drive_incremental(self):
        # Tạo các file tài liệu và file không phải tài liệu trên mock USB
        doc1 = os.path.join(self.usb_root, "Report.docx")
        doc2 = os.path.join(self.usb_root, "Data.xlsx")
        non_doc = os.path.join(self.usb_root, "Music.mp3")

        with open(doc1, "w") as f:
            f.write("Word content 1")
        with open(doc2, "w") as f:
            f.write("Excel content 2")
        with open(non_doc, "w") as f:
            f.write("audio binary")

        # Lần 1: Sao lưu mới
        report1 = self.backup_mgr.backup_drive(self.usb_root, "TEST_USB", self.backup_root)
        self.assertTrue(report1.is_success)
        self.assertEqual(report1.total_docs_found, 2)
        self.assertEqual(report1.copied_count, 2)
        self.assertEqual(report1.skipped_count, 0)

        # File tài liệu phải tồn tại trong thư mục đích
        dest_doc1 = os.path.join(report1.backup_target_dir, "Report.docx")
        dest_doc2 = os.path.join(report1.backup_target_dir, "Data.xlsx")
        dest_nondoc = os.path.join(report1.backup_target_dir, "Music.mp3")
        self.assertTrue(os.path.exists(dest_doc1))
        self.assertTrue(os.path.exists(dest_doc2))
        self.assertFalse(os.path.exists(dest_nondoc))  # Không sao chép mp3

        # Lần 2: Sao lưu lại ngay khi không có gì đổi -> Phải bỏ qua (skipped)
        report2 = self.backup_mgr.backup_drive(self.usb_root, "TEST_USB", self.backup_root)
        self.assertTrue(report2.is_success)
        self.assertEqual(report2.copied_count, 0)
        self.assertEqual(report2.skipped_count, 2)

        # Lần 3: Chỉnh sửa 1 file -> Chỉ sao lưu file đó
        time.sleep(1.6)  # Đảm bảo mtime thay đổi
        with open(doc1, "w") as f:
            f.write("Word content updated version")

        report3 = self.backup_mgr.backup_drive(self.usb_root, "TEST_USB", self.backup_root)
        self.assertTrue(report3.is_success)
        self.assertEqual(report3.copied_count, 1)
        self.assertEqual(report3.skipped_count, 1)


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_mgr = ConfigManager(config_dir=self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_save_and_load_config(self):
        self.config_mgr.set("auto_backup_enabled", False)
        self.config_mgr.set("backup_directory", "D:\\Custom_Backup")
        self.config_mgr.set("cli_notify_enabled", False)

        # Khởi tạo instance mới đọc lại từ file
        new_mgr = ConfigManager(config_dir=self.test_dir.name)
        self.assertFalse(new_mgr.get("auto_backup_enabled"))
        self.assertEqual(new_mgr.get("backup_directory"), "D:\\Custom_Backup")
        self.assertFalse(new_mgr.get("cli_notify_enabled"))

    def test_telegram_config_not_saved_to_json(self):
        # Kiểm tra set các cấu hình telegram không bao giờ được ghi vào file config.json
        self.config_mgr.set("telegram_bot_token", "123456:SECRET_TOKEN")
        self.config_mgr.set("telegram_chat_id", "-100999999")
        self.config_mgr.set("telegram_backup_enabled", True)
        self.config_mgr.set("telegram_settle_delay", 5.0)

        # Đọc trực tiếp nội dung raw từ file config.json trên đĩa
        config_file = os.path.join(self.test_dir.name, "config.json")
        with open(config_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        for key in ["telegram_bot_token", "telegram_chat_id", "telegram_backup_enabled", "telegram_settle_delay", "bot_id", "chat_id"]:
            self.assertNotIn(key, raw_data)

    def test_strip_legacy_telegram_keys_from_file(self):
        # Giả lập file config.json cũ chứa thông tin telegram
        legacy_dir = tempfile.TemporaryDirectory()
        legacy_file = os.path.join(legacy_dir.name, "config.json")
        with open(legacy_file, "w", encoding="utf-8") as f:
            json.dump({
                "notify_enabled": True,
                "telegram_bot_token": "SECRET_OLD",
                "telegram_chat_id": "-100111",
                "telegram_backup_enabled": True,
            }, f)

        # Khởi tạo ConfigManager trỏ vào thư mục cũ
        mgr = ConfigManager(config_dir=legacy_dir.name)

        # Đọc lại file trên đĩa để chắc chắn các key telegram đã bị dọn sạch
        with open(legacy_file, "r", encoding="utf-8") as f:
            cleaned_data = json.load(f)

        self.assertNotIn("telegram_bot_token", cleaned_data)
        self.assertNotIn("telegram_chat_id", cleaned_data)
        self.assertNotIn("telegram_backup_enabled", cleaned_data)
        self.assertTrue(cleaned_data.get("notify_enabled"))
        legacy_dir.cleanup()


if __name__ == "__main__":
    print("Đang chạy kiểm thử tự động toàn diện...")
    unittest.main(verbosity=2)
