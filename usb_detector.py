"""
Module phát hiện và theo dõi thiết bị USB trên hệ điều hành Windows.
Sử dụng Windows Kernel32 API và DeviceIoControl để phát hiện chính xác:
- Ổ USB Flash Drive (Removable)
- Ổ cứng/SSD di động cắm qua cổng USB (BusType USB)
"""

import os
import sys
import time
import shutil
import string
import ctypes
import threading
from ctypes import wintypes
from typing import Dict, Any, List, Optional, Callable

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Windows API Constants
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
BUS_TYPE_USB = 7


class STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [
        ("PropertyId", ctypes.c_int),
        ("QueryType", ctypes.c_int),
        ("AdditionalParameters", ctypes.c_byte * 1),
    ]


class STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_ulong),
        ("Size", ctypes.c_ulong),
        ("DeviceType", ctypes.c_byte),
        ("DeviceTypeModifier", ctypes.c_byte),
        ("RemovableMedia", ctypes.c_byte),
        ("CommandQueueing", ctypes.c_byte),
        ("VendorIdOffset", ctypes.c_ulong),
        ("ProductIdOffset", ctypes.c_ulong),
        ("ProductRevisionOffset", ctypes.c_ulong),
        ("SerialNumberOffset", ctypes.c_ulong),
        ("BusType", ctypes.c_int),
        ("RawPropertiesLength", ctypes.c_ulong),
        ("RawDeviceProperties", ctypes.c_byte * 2048),
    ]


def format_bytes(size_bytes: int) -> str:
    """Chuyển đổi số bytes sang định dạng người đọc (KB, MB, GB, TB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    val = float(size_bytes)
    while val >= 1024.0 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    return f"{val:.1f} {units[idx]}"


def _get_string_at_offset(buf: ctypes.Array, offset: int) -> str:
    """Trích xuất chuỗi ASCII kết thúc bằng null từ raw buffer."""
    if offset <= 0 or offset >= len(buf):
        return ""
    end = offset
    while end < len(buf) and buf[end] != 0:
        end += 1
    try:
        raw_part = bytes(buf[offset:end])
        return raw_part.decode("ascii", errors="ignore").strip()
    except Exception:
        return ""


def get_drive_hardware_info(drive_letter: str) -> Dict[str, Any]:
    """
    Truy vấn thông tin phần cứng ổ đĩa qua DeviceIoControl:
    Xác định BusType (USB) và tên Vendor / Product nếu có.
    """
    clean_letter = drive_letter.rstrip(":\\/")
    device_path = f"\\\\.\\{clean_letter}:"

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(
        device_path,
        0,  # Không cần quyền Admin, chỉ truy vấn thuộc tính thiết bị
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )

    is_usb = False
    vendor = ""
    product = ""
    bus_type = -1

    if handle != -1 and handle != 0:
        try:
            query = STORAGE_PROPERTY_QUERY(0, 0)
            desc = STORAGE_DEVICE_DESCRIPTOR()
            bytes_returned = ctypes.c_ulong()

            res = kernel32.DeviceIoControl(
                handle,
                IOCTL_STORAGE_QUERY_PROPERTY,
                ctypes.byref(query),
                ctypes.sizeof(query),
                ctypes.byref(desc),
                ctypes.sizeof(desc),
                ctypes.byref(bytes_returned),
                None,
            )

            if res:
                bus_type = desc.BusType
                if bus_type == BUS_TYPE_USB:
                    is_usb = True
                
                # Trích xuất tên nhà sản xuất & dòng sản phẩm
                raw_buf = desc.RawDeviceProperties
                vendor = _get_string_at_offset(raw_buf, desc.VendorIdOffset)
                product = _get_string_at_offset(raw_buf, desc.ProductIdOffset)
        finally:
            kernel32.CloseHandle(handle)

    return {
        "is_usb_bus": is_usb,
        "bus_type": bus_type,
        "vendor": vendor,
        "product": product,
    }


def get_drive_info(drive_letter: str) -> Optional[Dict[str, Any]]:
    """
    Lấy thông tin chi tiết của 1 ổ đĩa (Label, Filesystem, Dung lượng, Loại ổ).
    """
    clean_letter = drive_letter.rstrip(":\\/").upper()
    drive_path = f"{clean_letter}:\\"

    kernel32 = ctypes.windll.kernel32
    drive_type = kernel32.GetDriveTypeW(drive_path)

    # Nếu không phải ổ đĩa hợp lệ thì bỏ qua
    if drive_type in (DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR):
        return None

    # Lấy nhãn ổ đĩa và định dạng tập tin
    vol_buf = ctypes.create_unicode_buffer(260)
    fs_buf = ctypes.create_unicode_buffer(260)
    serial = ctypes.c_ulong()
    max_len = ctypes.c_ulong()
    flags = ctypes.c_ulong()

    success = kernel32.GetVolumeInformationW(
        drive_path,
        vol_buf,
        ctypes.sizeof(vol_buf),
        ctypes.byref(serial),
        ctypes.byref(max_len),
        ctypes.byref(flags),
        fs_buf,
        ctypes.sizeof(fs_buf),
    )

    label = vol_buf.value if success else ""
    fs = fs_buf.value if success else ""

    # Lấy dung lượng
    total_bytes, free_bytes, used_bytes = 0, 0, 0
    try:
        usage = shutil.disk_usage(drive_path)
        total_bytes = usage.total
        free_bytes = usage.free
        used_bytes = usage.used
    except Exception:
        pass

    # Truy vấn thông tin bus USB
    hw_info = get_drive_hardware_info(clean_letter)
    is_removable = (drive_type == DRIVE_REMOVABLE)
    is_usb = is_removable or hw_info["is_usb_bus"]

    # Đặt tên hiển thị dễ hiểu
    display_name = label
    if not display_name:
        if hw_info["product"]:
            display_name = f"{hw_info['vendor']} {hw_info['product']}".strip()
        else:
            display_name = "USB Drive" if is_usb else f"Local Disk ({clean_letter}:)"

    return {
        "drive": drive_path,
        "letter": clean_letter,
        "label": label or display_name,
        "display_name": display_name,
        "file_system": fs or "N/A",
        "drive_type": drive_type,
        "is_removable": is_removable,
        "is_usb": is_usb,
        "vendor": hw_info["vendor"],
        "product": hw_info["product"],
        "bus_type": hw_info["bus_type"],
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "total_space_str": format_bytes(total_bytes),
        "used_space_str": format_bytes(used_bytes),
        "free_space_str": format_bytes(free_bytes),
    }


def list_usb_drives() -> Dict[str, Dict[str, Any]]:
    """
    Quét và trả về tất cả các thiết bị USB đang được kết nối với máy tính.
    """
    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    usb_drives = {}

    for i in range(26):
        if bitmask & (1 << i):
            letter = chr(ord("A") + i)
            info = get_drive_info(letter)
            if info and info["is_usb"]:
                usb_drives[letter] = info

    return usb_drives


class USBDetector:
    """
    Lớp chạy ngầm quét và lắng nghe sự kiện cắm/rút USB.
    """

    def __init__(
        self,
        on_connected: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_disconnected: Optional[Callable[[Dict[str, Any]], None]] = None,
        poll_interval: float = 1.0,
    ):
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_usbs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get_current_usbs(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._current_usbs)

    def start(self):
        """Khởi động tiến trình giám sát ngầm."""
        if self._running:
            return
        self._running = True

        # Quét trạng thái ban đầu
        self._current_usbs = list_usb_drives()

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="USBMonitorThread")
        self._thread.start()

    def stop(self):
        """Dừng tiến trình giám sát."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        while self._running:
            try:
                new_usbs = list_usb_drives()

                with self._lock:
                    old_keys = set(self._current_usbs.keys())
                    new_keys = set(new_usbs.keys())

                    # Phát hiện USB mới cắm vào
                    connected_keys = new_keys - old_keys
                    for letter in connected_keys:
                        # Chờ 0.5s để Windows hoàn tất đọc metadata phân vùng
                        time.sleep(0.5)
                        updated_info = get_drive_info(letter) or new_usbs[letter]
                        self._current_usbs[letter] = updated_info
                        if self.on_connected:
                            try:
                                self.on_connected(updated_info)
                            except Exception as e:
                                print(f"[USBDetector] Lỗi khi gọi callback cắm USB: {e}")

                    # Phát hiện USB đã rút ra
                    disconnected_keys = old_keys - new_keys
                    for letter in disconnected_keys:
                        lost_info = self._current_usbs.pop(letter, {"drive": f"{letter}:\\", "label": "USB Drive"})
                        if self.on_disconnected:
                            try:
                                self.on_disconnected(lost_info)
                            except Exception as e:
                                print(f"[USBDetector] Lỗi khi gọi callback rút USB: {e}")

            except Exception as e:
                print(f"[USBDetector] Lỗi trong vòng lặp giám sát: {e}")

            time.sleep(self.poll_interval)


if __name__ == "__main__":
    print("=== KIỂM TRA QUÉT THIẾT BỊ USB ===")
    usbs = list_usb_drives()
    if not usbs:
        print("Hiện tại không có thiết bị USB nào cắm vào.")
    else:
        for letter, info in usbs.items():
            print(f"- Ổ {info['drive']} | Nhãn: {info['label']} | Dung lượng: {info['free_space_str']} trống / {info['total_space_str']} | Định dạng: {info['file_system']}")

    print("\nKhởi động detector kiểm tra trong 5 giây...")
    detector = USBDetector(
        on_connected=lambda info: print(f"[EVENT] Đã cắm: {info['drive']}"),
        on_disconnected=lambda info: print(f"[EVENT] Đã rút: {info['drive']}"),
        poll_interval=1.0,
    )
    detector.start()
    time.sleep(3.0)
    detector.stop()
    print("Kiểm tra hoàn tất.")
