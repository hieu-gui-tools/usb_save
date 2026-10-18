"""
Điểm khởi động chính của ứng dụng USB Detector & Notifier.
Hỗ trợ các chế độ chạy:
- Mặc định: Mở giao diện đồ họa GUI (Tkinter)
- --tray: Khởi chạy và thu nhỏ ngay vào Khay hệ thống (System Tray)
- --cli: Chạy ngầm dạng dòng lệnh Console
"""

import sys
import time
import argparse
from typing import Dict, Any, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from notifier import USBNotifier
from usb_detector import USBDetector, list_usb_drives
from usb_scanner import USBScanner
from usb_backup import USBBackupManager
from config_manager import ConfigManager
from telegram_backup import TelegramBackupManager
from folder_watcher import FolderWatcher


def run_cli_mode(
    auto_scan: bool = True,
    auto_backup: bool = True,
    backup_dir: str = None,
    notify: bool = True,
    telegram_enabled: bool = False,
    telegram_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    telegram_settle_delay: float = 2.5,
):
    """Chạy ở chế độ dòng lệnh Console."""
    config_mgr = ConfigManager()
    notifier = USBNotifier()
    scanner = USBScanner()
    backup_mgr = USBBackupManager()

    dest_backup_dir = backup_dir or config_mgr.get("backup_directory")

    is_tg_on = bool(telegram_enabled)
    tg_token = telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    tg_delay = telegram_settle_delay

    def tg_log(msg: str, tag: str = "INFO"):
        ts = time.strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{ts} [Telegram] {msg}")

    tg_mgr = TelegramBackupManager(on_log=tg_log)
    tg_mgr.configure(bot_token=tg_token, chat_id=tg_chat, enabled=is_tg_on, settle_delay=tg_delay)

    folder_watcher = None
    if is_tg_on and tg_token and tg_chat:
        tg_mgr.start()
        folder_watcher = FolderWatcher(
            watch_dir=dest_backup_dir,
            on_file_changed=lambda a, r: tg_mgr.enqueue_file(a, r),
            on_log=tg_log,
        )
        folder_watcher.start()

    print("=" * 60)
    print("🛡️  USB DETECTOR & BACKUP - CHẾ ĐỘ DÒNG LỆNH (CLI)")
    print("   Lá chắn bảo mật:  " + ("ĐANG BẬT" if auto_scan else "TẮT"))
    print("   Sao lưu tài liệu: " + ("ĐANG BẬT (Word, PDF, Excel, PowerPoint)" if auto_backup else "TẮT"))
    print("   Sao lưu Telegram: " + ("ĐANG BẬT (Đồng bộ nhóm Telegram)" if (is_tg_on and tg_token and tg_chat) else "TẮT"))
    print("   Thông báo Windows: " + ("ĐANG BẬT" if notify else "TẮT (Chế độ im lặng)"))
    if auto_backup:
        print(f"   Thư mục lưu:     {dest_backup_dir}")
    print("=" * 60)


    # Hiển thị các USB hiện có
    existing = list_usb_drives()
    if existing:
        print(f"Đang có {len(existing)} thiết bị USB được cắm:")
        for letter, info in existing.items():
            print(f"  - [{info['drive']}] {info['label']} ({info['free_space_str']} trống / {info['total_space_str']})")
    else:
        print("Chưa có thiết bị USB nào được kết nối.")

    print("\nĐang lắng nghe sự kiện cắm/rút USB trong thời gian thực...")
    print("Nhấn Ctrl + C để dừng chương trình.\n")

    def on_connect(info: Dict[str, Any]):
        drive = info.get("drive", "")
        label = info.get("label", "USB Drive")
        free = info.get("free_space_str", "N/A")
        total = info.get("total_space_str", "N/A")
        fs = info.get("file_system", "N/A")
        timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} 🔌 PHÁT HIỆN CẮM USB: Ổ {drive} ({label}) | Dung lượng: {free} / {total} [{fs}]")
        if notify:
            notifier.notify_connected(info)

        if auto_scan:
            print(f"{timestamp} 🔍 Đang quét bảo mật kiểm tra autorun & mã độc trên ổ {drive}...")
            scan_res = scanner.scan_drive(drive, auto_quarantine=True)
            if scan_res.is_safe:
                print(f"{timestamp} ✅ Ổ {drive} an toàn! Đã quét {scan_res.scanned_files_count} tệp.")
            else:
                print(f"{timestamp} 🚨 CẢNH BÁO: Phát hiện {scan_res.threat_count} mối đe dọa trên ổ {drive}!")
                for t in scan_res.threats:
                    q_str = "ĐÃ CÁCH LY" if t.quarantined else "CHƯA CÁCH LY"
                    print(f"   ❌ [{t.threat_type}] {t.filename} - {t.description} ({q_str})")
                if notify:
                    notifier.notify_threat_detected(drive, label, scan_res.threats)

        if auto_backup:
            print(f"{timestamp} 💾 Đang sao lưu tài liệu văn phòng từ ổ {drive}...")
            report = backup_mgr.backup_drive(drive, label, dest_backup_dir)
            if report.is_success:
                print(f"{timestamp} ✅ {report.summary()}")
                if report.copied_count > 0 and notify:
                    notifier.notify_backup_completed(
                        drive=drive,
                        label=label,
                        copied_count=report.copied_count,
                        total_count=report.total_docs_found,
                        bytes_str=report.copied_bytes_str,
                        target_dir=report.backup_target_dir,
                    )
            else:
                print(f"{timestamp} ⚠️ Lỗi sao lưu: {report.error_message}")

    def on_disconnect(info: Dict[str, Any]):
        drive = info.get("drive", "")
        label = info.get("label", "USB Drive")
        timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} ⚠️ PHÁT HIỆN RÚT USB: Ổ {drive} ({label}) đã bị ngắt kết nối.")
        if notify:
            notifier.notify_disconnected(info)

    detector = USBDetector(on_connected=on_connect, on_disconnected=on_disconnect, poll_interval=1.0)
    detector.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nĐang dừng giám sát...")
        detector.stop()
        if folder_watcher:
            folder_watcher.stop()
        if tg_mgr:
            tg_mgr.stop()
        print("Đã thoát chương trình an toàn.")


def run_gui_mode(start_in_tray: bool = False):
    """Chạy ở chế độ giao diện đồ họa."""
    import tkinter as tk
    from gui import USBDetectorApp

    root = tk.Tk()
    app = USBDetectorApp(root)

    if start_in_tray:
        root.after(100, app.hide_to_tray)

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Ứng dụng tự động phát hiện USB cắm/rút, bảo mật và sao lưu tài liệu trên Windows")
    parser.add_argument("--cli", action="store_true", help="Chạy chế độ console CLI (không mở cửa sổ GUI)")
    parser.add_argument("--tray", action="store_true", help="Khởi động và ẩn ngay xuống Khay hệ thống (System Tray)")
    parser.add_argument("--no-scan", action="store_true", help="Tắt tính năng tự động quét bảo mật")
    parser.add_argument("--no-backup", action="store_true", help="Tắt tính năng tự động sao lưu tài liệu")
    parser.add_argument("--backup-dir", type=str, default=None, help="Đường dẫn thư mục sao lưu tài liệu")
    parser.add_argument("--telegram", action="store_true", help="Bật tính năng sao lưu tự động lên nhóm Telegram")
    parser.add_argument("--no-telegram", action="store_true", help="Tắt tính năng sao lưu tự động lên nhóm Telegram")
    parser.add_argument("--telegram-token", type=str, default=None, help="Telegram Bot Token (hoặc đặt biến môi trường TELEGRAM_BOT_TOKEN)")
    parser.add_argument("--telegram-chat-id", type=str, default=None, help="Telegram Chat ID (hoặc đặt biến môi trường TELEGRAM_CHAT_ID)")
    parser.add_argument("--no-notify", action="store_true", help="Tắt thông báo Windows Toast khi chạy chế độ CLI")
    parser.add_argument("--notify", action="store_true", help="Bật thông báo Windows Toast khi chạy chế độ CLI (ghi đè cấu hình)")

    args = parser.parse_args()

    if args.cli:
        config_mgr = ConfigManager()
        # Đọc cấu hình mặc định cho CLI
        cli_notify = config_mgr.get("cli_notify_enabled", True)
        if args.no_notify:
            cli_notify = False
        elif args.notify:
            cli_notify = True

        tg_enabled = False
        if args.telegram:
            tg_enabled = True
        elif args.no_telegram:
            tg_enabled = False

        run_cli_mode(
            auto_scan=(not args.no_scan),
            auto_backup=(not args.no_backup),
            backup_dir=args.backup_dir,
            notify=cli_notify,
            telegram_enabled=tg_enabled,
            telegram_token=args.telegram_token,
            telegram_chat_id=args.telegram_chat_id,
        )
    else:
        run_gui_mode(start_in_tray=args.tray)



if __name__ == "__main__":
    main()
