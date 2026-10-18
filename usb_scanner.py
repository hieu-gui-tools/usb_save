"""
Module quét bảo mật và ngăn chặn mã độc trên thiết bị USB:
- Phát hiện và vô hiệu hóa autorun.inf
- Phát hiện Shortcut Virus (.lnk trỏ lệnh thực thi console/script)
- Phát hiện file ngụy trang đuôi kép (*.pdf.exe, *.jpg.vbs, ...)
- Phát hiện file script/thực thi nguy hiểm (*.vbs, *.js, *.wsf, *.hta, *.scr, *.pif)
- Cách ly an toàn (Quarantine) và phục hồi
- Tiêm phòng chống lây nhiễm autorun (Immunization)
- Khôi phục file/thư mục bị virus ẩn đi (Unhide)
"""

import os
import sys
import re
import json
import shutil
import ctypes
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Danh sách phần mở rộng nguy hiểm cao trên USB
DANGEROUS_EXTENSIONS = {
    ".vbs", ".js", ".jse", ".wsf", ".wsh", ".hta", ".scr", ".pif", ".cmd", ".bat", ".ps1"
}

# Các phần mở rộng giả mạo thường gặp ở định dạng đuôi kép
FAKE_DOUBLE_EXTS = {
    ".pdf.exe", ".doc.exe", ".docx.exe", ".xls.exe", ".xlsx.exe",
    ".ppt.exe", ".pptx.exe", ".jpg.exe", ".jpeg.exe", ".png.exe",
    ".zip.exe", ".rar.exe", ".mp4.exe", ".mp3.exe", ".txt.exe",
    ".pdf.vbs", ".doc.vbs", ".jpg.vbs", ".pdf.scr", ".docx.scr"
}

# Từ khóa lệnh độc hại thường thấy trong Shortcut virus (.lnk)
SUSPICIOUS_LNK_KEYWORDS = [
    b"cmd.exe", b"powershell", b"wscript", b"cscript", b"mshta",
    b"rundll32", b"certutil", b"bitsadmin", b"regsvr32", b"curl.exe"
]

# Thư mục hệ thống giả mạo hoặc thư mục rác hay bị virus ẩn nấp
SUSPICIOUS_FOLDERS = {
    "recycler", "$recycle.bin", ".trashes", "system volume information"
}


class ThreatInfo:
    """Mô tả một mối đe dọa được tìm thấy."""

    def __init__(self, file_path: str, threat_type: str, severity: str, description: str):
        self.file_path = file_path
        self.filename = os.path.basename(file_path)
        self.threat_type = threat_type  # 'AUTORUN', 'SHORTCUT_WORM', 'DOUBLE_EXT', 'DANGEROUS_SCRIPT', 'HIDDEN_EXEC'
        self.severity = severity        # 'CRITICAL', 'HIGH', 'MEDIUM'
        self.description = description
        self.quarantined = False
        self.quarantine_path = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "filename": self.filename,
            "threat_type": self.threat_type,
            "severity": self.severity,
            "description": self.description,
            "quarantined": self.quarantined,
            "quarantine_path": self.quarantine_path,
        }


class ScanResult:
    """Kết quả sau khi quét một ổ đĩa USB."""

    def __init__(self, drive_path: str):
        self.drive_path = drive_path
        self.scanned_files_count = 0
        self.threats: List[ThreatInfo] = []
        self.scan_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.has_autorun = False

    @property
    def threat_count(self) -> int:
        return len(self.threats)

    @property
    def is_safe(self) -> bool:
        return len(self.threats) == 0


class USBScanner:
    """Trình quét và bảo vệ thiết bị USB."""

    def __init__(self, quarantine_folder_name: str = ".usb_quarantine"):
        self.quarantine_folder_name = quarantine_folder_name

    def scan_drive(
        self,
        drive_path: str,
        auto_quarantine: bool = True,
        max_depth: int = 3,
        on_progress: Optional[callable] = None,
    ) -> ScanResult:
        """
        Quét ổ đĩa USB để phát hiện autorun và mã độc hại.
        """
        clean_drive = drive_path.rstrip("\\/") + "\\"
        result = ScanResult(clean_drive)

        if not os.path.exists(clean_drive):
            return result

        # 1. Kiểm tra trực tiếp file autorun.inf ở thư mục gốc
        autorun_path = os.path.join(clean_drive, "autorun.inf")
        if os.path.isfile(autorun_path):
            result.has_autorun = True
            threat = self._analyze_autorun(autorun_path)
            result.threats.append(threat)
            if auto_quarantine:
                self.quarantine_file(clean_drive, threat)

        # 2. Duyệt các tập tin trên USB
        try:
            for root, dirs, files in os.walk(clean_drive):
                # Tính độ sâu thư mục để tránh quét quá lâu trên USB dung lượng lớn
                rel_path = os.path.relpath(root, clean_drive)
                depth = 0 if rel_path == "." else len(rel_path.split(os.sep))
                if depth > max_depth:
                    continue

                # Bỏ qua thư mục cách ly của ứng dụng
                if self.quarantine_folder_name.lower() in root.lower():
                    continue

                for fname in files:
                    result.scanned_files_count += 1
                    fpath = os.path.join(root, fname)

                    # Bỏ qua nếu là autorun.inf (đã xử lý ở bước 1)
                    if fname.lower() == "autorun.inf":
                        continue

                    threat = self._inspect_file(fpath, root, clean_drive)
                    if threat:
                        result.threats.append(threat)
                        if auto_quarantine:
                            self.quarantine_file(clean_drive, threat)

                    if on_progress and (result.scanned_files_count % 50 == 0):
                        on_progress(result.scanned_files_count, fpath)

        except Exception as e:
            print(f"[USBScanner Error] Lỗi khi quét thư mục {clean_drive}: {e}")

        return result

    def _analyze_autorun(self, autorun_path: str) -> ThreatInfo:
        """Phân tích nội dung file autorun.inf."""
        desc = "Phát hiện file autorun.inf tự động kích hoạt mã độc khi cắm USB."
        try:
            with open(autorun_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                # Tìm lệnh mở file thực thi
                match = re.search(r"(?:open|shellexecute|run)\s*=\s*(.+)", content, re.IGNORECASE)
                if match:
                    target = match.group(1).strip()
                    desc += f" (Cố gắng khởi chạy: '{target}')"
        except Exception:
            pass

        return ThreatInfo(
            file_path=autorun_path,
            threat_type="AUTORUN",
            severity="CRITICAL",
            description=desc,
        )

    def _inspect_file(self, fpath: str, root: str, drive_path: str) -> Optional[ThreatInfo]:
        """Kiểm tra từng tập tin cụ thể theo các chữ ký và hành vi nguy hiểm."""
        fname = os.path.basename(fpath)
        fname_lower = fname.lower()
        root_lower = root.lower()
        is_in_root = (os.path.abspath(root).lower() == os.path.abspath(drive_path).lower())

        # 1. Kiểm tra tập tin đuôi kép (Double Extension)
        for dbl_ext in FAKE_DOUBLE_EXTS:
            if fname_lower.endswith(dbl_ext):
                return ThreatInfo(
                    file_path=fpath,
                    threat_type="DOUBLE_EXT",
                    severity="CRITICAL",
                    description=f"File ngụy trang đuôi kép độc hại '{fname}'.",
                )

        # 2. Kiểm tra Shortcut virus (.lnk)
        if fname_lower.endswith(".lnk"):
            is_bad, kw = self._check_suspicious_lnk(fpath)
            if is_bad:
                return ThreatInfo(
                    file_path=fpath,
                    threat_type="SHORTCUT_WORM",
                    severity="CRITICAL",
                    description=f"Shortcut Virus (.lnk) kích hoạt lệnh hệ thống nguy hiểm ('{kw}').",
                )

        # 3. Kiểm tra kịch bản script nguy hiểm ở thư mục gốc hoặc thư mục ẩn
        _, ext = os.path.splitext(fname_lower)
        if ext in DANGEROUS_EXTENSIONS:
            # Script nằm ở thư mục gốc USB cực kỳ đáng ngờ
            if is_in_root:
                return ThreatInfo(
                    file_path=fpath,
                    threat_type="DANGEROUS_SCRIPT",
                    severity="HIGH",
                    description=f"File kịch bản thực thi nguy hiểm '{fname}' nằm ở thư mục gốc USB.",
                )
            # Script nằm trong thư mục rác / hệ thống giả mạo
            for susp_dir in SUSPICIOUS_FOLDERS:
                if susp_dir in root_lower:
                    return ThreatInfo(
                        file_path=fpath,
                        threat_type="DANGEROUS_SCRIPT",
                        severity="CRITICAL",
                        description=f"File script độc hại giấu trong thư mục '{susp_dir}'.",
                    )

        # 4. Kiểm tra file thực thi nằm trong các thư mục rác/giả mạo (RECYCLER, Trashes)
        if ext in (".exe", ".dll", ".com"):
            for susp_dir in SUSPICIOUS_FOLDERS:
                if susp_dir in root_lower:
                    return ThreatInfo(
                        file_path=fpath,
                        threat_type="HIDDEN_EXEC",
                        severity="CRITICAL",
                        description=f"File thực thi đáng ngờ ẩn nấp trong thư mục '{susp_dir}'.",
                    )

        return None

    def _check_suspicious_lnk(self, lnk_path: str) -> Tuple[bool, Optional[str]]:
        """Đọc và kiểm tra nội dung nhị phân của file .lnk để phát hiện lệnh thực thi ngầm."""
        try:
            with open(lnk_path, "rb") as f:
                content = f.read(16384)  # Đọc 16KB đầu tiên là đủ tìm commandline
                content_lower = content.lower()
                for kw in SUSPICIOUS_LNK_KEYWORDS:
                    if kw in content_lower:
                        return True, kw.decode("ascii", errors="ignore")
        except Exception:
            pass
        return False, None

    def quarantine_file(self, drive_path: str, threat: ThreatInfo) -> bool:
        """
        Cách ly tập tin độc hại:
        - Tạo thư mục cách ly ẩn an toàn trên USB (.usb_quarantine).
        - Di chuyển file vào và đổi đuôi sang .quarantine (vô hiệu hóa thực thi).
        - Ghi metadata phục vụ khôi phục nếu cần.
        """
        if threat.quarantined:
            return True

        clean_drive = drive_path.rstrip("\\/") + "\\"
        quarantine_dir = os.path.join(clean_drive, self.quarantine_folder_name)

        try:
            os.makedirs(quarantine_dir, exist_ok=True)
            # Đặt thuộc tính ẩn cho thư mục cách ly
            ctypes.windll.kernel32.SetFileAttributesW(quarantine_dir, 0x02)  # FILE_ATTRIBUTE_HIDDEN

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = f"{timestamp}_{threat.filename}.quarantine"
            dest_path = os.path.join(quarantine_dir, safe_name)

            # Gỡ bỏ các thuộc tính Read-only/System trước khi di chuyển
            try:
                ctypes.windll.kernel32.SetFileAttributesW(threat.file_path, 0x80)  # FILE_ATTRIBUTE_NORMAL
            except Exception:
                pass

            # Di chuyển file vào khu vực cách ly
            shutil.move(threat.file_path, dest_path)

            # Lưu file metadata đi kèm
            meta_path = dest_path + ".meta"
            meta_data = {
                "original_path": threat.file_path,
                "filename": threat.filename,
                "threat_type": threat.threat_type,
                "severity": threat.severity,
                "description": threat.description,
                "quarantine_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta_data, mf, indent=2, ensure_ascii=False)

            threat.quarantined = True
            threat.quarantine_path = dest_path
            return True

        except Exception as e:
            print(f"[Quarantine Error] Không thể cách ly file {threat.file_path}: {e}")
            return False

    def list_quarantined_files(self, drive_path: str) -> List[Dict[str, Any]]:
        """Lấy danh sách các file hiện đang bị cách ly trên USB."""
        clean_drive = drive_path.rstrip("\\/") + "\\"
        quarantine_dir = os.path.join(clean_drive, self.quarantine_folder_name)
        items = []

        if not os.path.isdir(quarantine_dir):
            return items

        try:
            for fname in os.listdir(quarantine_dir):
                if fname.endswith(".meta"):
                    meta_path = os.path.join(quarantine_dir, fname)
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            data["quarantine_file"] = meta_path[:-5]  # Bỏ đuôi .meta
                            items.append(data)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Quarantine List Error] {e}")

        return items

    def restore_quarantined_file(self, meta_item: Dict[str, Any]) -> bool:
        """Khôi phục tập tin từ khu vực cách ly về vị trí ban đầu."""
        quarantine_file = meta_item.get("quarantine_file", "")
        original_path = meta_item.get("original_path", "")

        if not os.path.exists(quarantine_file):
            return False

        try:
            parent_dir = os.path.dirname(original_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            shutil.move(quarantine_file, original_path)

            meta_file = quarantine_file + ".meta"
            if os.path.exists(meta_file):
                os.remove(meta_file)
            return True
        except Exception as e:
            print(f"[Restore Error] Không thể khôi phục {quarantine_file}: {e}")
            return False

    def immunize_drive(self, drive_path: str) -> Tuple[bool, str]:
        """
        Tiêm phòng USB chống lây nhiễm autorun:
        Tạo thư mục khóa tên 'autorun.inf' có thuộc tính ẩn/chỉ đọc/hệ thống.
        Khi đã có thư mục 'autorun.inf', virus không thể tạo tệp autorun.inf mới.
        """
        clean_drive = drive_path.rstrip("\\/") + "\\"
        target_path = os.path.join(clean_drive, "autorun.inf")

        try:
            # Nếu đang tồn tại file autorun.inf, xóa hoặc di chuyển trước
            if os.path.isfile(target_path):
                ctypes.windll.kernel32.SetFileAttributesW(target_path, 0x80)  # NORMAL
                os.remove(target_path)

            if not os.path.exists(target_path):
                os.makedirs(target_path, exist_ok=True)
                # Tạo một thư mục con bảo vệ chống xóa bên trong
                sub_lock = os.path.join(target_path, "immunized_lock.protect")
                os.makedirs(sub_lock, exist_ok=True)

                # Thiết lập thuộc tính READONLY (0x01) + HIDDEN (0x02) + SYSTEM (0x04)
                ctypes.windll.kernel32.SetFileAttributesW(target_path, 0x01 | 0x02 | 0x04)
                return True, "Tiêm phòng USB thành công! Đã tạo lá chắn khóa autorun.inf an toàn."
            else:
                return True, "USB đã được tiêm phòng từ trước (thư mục autorun.inf đã tồn tại)."

        except Exception as e:
            return False, f"Lỗi tiêm phòng: {e}"

    def unhide_files(self, drive_path: str) -> Tuple[bool, str]:
        """
        Khôi phục các tệp và thư mục bị virus shortcut làm ẩn:
        Chạy lệnh gỡ bỏ thuộc tính ẩn (-h), hệ thống (-s), chỉ đọc (-r).
        """
        clean_drive = drive_path.rstrip("\\/") + "\\"
        try:
            # Dùng lệnh attrib của Windows: attrib -h -s -r /s /d
            cmd = f'attrib -h -s -r "{clean_drive}*.*" /s /d'
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return True, "Đã khôi phục toàn bộ các tệp và thư mục bị ẩn trên USB!"
        except Exception as e:
            return False, f"Lỗi khi hiển thị file ẩn: {e}"


if __name__ == "__main__":
    scanner = USBScanner()
    print("USB Scanner module loaded successfully.")
