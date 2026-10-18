"""
Module quản lý phát thông báo Windows Toast Notification cho các sự kiện USB.
"""

import os
import sys
import subprocess
from typing import Dict, Any, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from winotify import Notification, audio


class USBNotifier:
    APP_ID = "USB Detector & Notifier"

    def __init__(self, app_id: Optional[str] = None):
        self.app_id = app_id or self.APP_ID

    def notify_connected(self, usb_info: Dict[str, Any]) -> bool:
        """
        Gửi thông báo khi có USB mới được cắm vào.
        """
        drive = usb_info.get("drive", "")
        label = usb_info.get("label", "USB Drive") or "USB Drive"
        free = usb_info.get("free_space_str", "N/A")
        total = usb_info.get("total_space_str", "N/A")
        fs = usb_info.get("file_system", "FAT32")

        title = f"🔌 Đã phát hiện USB: {drive} ({label})"
        msg = f"Định dạng: {fs} | Còn trống: {free} / {total}\nNhấn vào để mở ổ đĩa trong Explorer."

        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=msg,
                duration="short"
            )
            toast.set_audio(audio.Default, loop=False)

            # Thêm nút bấm mở trực tiếp thư mục USB
            drive_clean = drive.rstrip("\\")
            toast.add_actions(label="Mở ổ đĩa", launch=drive)

            toast.show()
            return True
        except Exception as e:
            print(f"[Notifier Error] Không thể gửi thông báo cắm USB: {e}")
            return False

    def notify_disconnected(self, usb_info: Dict[str, Any]) -> bool:
        """
        Gửi thông báo khi USB bị rút ra.
        """
        drive = usb_info.get("drive", "")
        label = usb_info.get("label", "USB Drive") or "USB Drive"

        title = f"⚠️ USB đã ngắt kết nối: {drive}"
        msg = f"Thiết bị '{label}' ({drive}) đã được rút khỏi máy tính."

        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=msg,
                duration="short"
            )
            toast.set_audio(audio.Reminder, loop=False)
            toast.show()
            return True
        except Exception as e:
            print(f"[Notifier Error] Không thể gửi thông báo rút USB: {e}")
            return False

    def notify_threat_detected(self, drive: str, label: str, threats: list) -> bool:
        """
        Gửi thông báo cảnh báo khẩn cấp khi phát hiện autorun hoặc mã độc hại trên USB.
        """
        threat_count = len(threats)
        title = f"🚨 NGUY CƠ: Đã chặn {threat_count} mã độc trên {drive} ({label})!"

        # Liệt kê tóm tắt tối đa 2 mối đe dọa
        threat_summaries = []
        for t in threats[:2]:
            fname = getattr(t, "filename", str(t))
            ttype = getattr(t, "threat_type", "MÃ ĐỘC")
            threat_summaries.append(f"• {fname} [{ttype}]")

        details_str = "\n".join(threat_summaries)
        if threat_count > 2:
            details_str += f"\n• ...và {threat_count - 2} mối đe dọa khác."

        msg = f"Hệ thống đã tự động cách ly các tệp nguy hiểm:\n{details_str}\nNhấp để xem chi tiết."

        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=msg,
                duration="long"
            )
            toast.set_audio(audio.Reminder, loop=False)
            toast.show()
            return True
        except Exception as e:
            print(f"[Notifier Error] Không thể gửi cảnh báo mã độc: {e}")
            return False

    def notify_scan_clean(self, drive: str, label: str, scanned_count: int) -> bool:
        """
        Gửi thông báo khi quét xong và USB hoàn toàn sạch.
        """
        title = f"🛡️ USB An Toàn: {drive} ({label})"
        msg = f"Đã quét {scanned_count} tệp tin. Không phát hiện autorun hay mã độc hại nào!"

        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=msg,
                duration="short"
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            return True
        except Exception as e:
            print(f"[Notifier Error] Không thể gửi thông báo quét sạch: {e}")
            return False

    def notify_backup_completed(
        self, drive: str, label: str, copied_count: int, total_count: int, bytes_str: str, target_dir: str
    ) -> bool:
        """
        Gửi thông báo khi hoàn tất sao lưu tài liệu vào máy tính.
        """
        title = f"💾 Sao lưu tài liệu hoàn tất: {drive} ({label})"
        if copied_count > 0:
            msg = f"Đã sao lưu mới {copied_count} tài liệu ({bytes_str}).\nTổng tài liệu: {total_count}. Nhấp để mở thư mục lưu."
        else:
            msg = f"Tất cả {total_count} tài liệu đã được sao lưu từ trước và đồng bộ đầy đủ!"

        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=msg,
                duration="short"
            )
            toast.set_audio(audio.Default, loop=False)

            if os.path.exists(target_dir):
                toast.add_actions(label="Mở thư mục sao lưu", launch=target_dir)

            toast.show()
            return True
        except Exception as e:
            print(f"[Notifier Error] Không thể gửi thông báo sao lưu: {e}")
            return False

    def notify_test(self) -> bool:
        """
        Gửi thông báo thử nghiệm.
        """
        try:
            toast = Notification(
                app_id=self.app_id,
                title="🔔 Kiểm tra thông báo USB",
                msg="Hệ thống thông báo hoạt động bình thường! Sẵn sàng phát hiện USB.",
                duration="short"
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            return True
        except Exception as e:
            print(f"[Notifier Error] Lỗi kiểm tra thông báo: {e}")
            return False


if __name__ == "__main__":
    notifier = USBNotifier()
    print("Đang gửi thông báo kiểm tra...")
    success = notifier.notify_test()
    print("Kết quả:", "Thành công" if success else "Thất bại")
