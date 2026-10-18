"""
Module tự động sao lưu tài liệu văn phòng từ thiết bị USB vào máy tính.
Chỉ lọc và sao chép các tệp tài liệu:
- Word: .docx, .doc, .docm, .dotx, .dot
- PDF: .pdf
- Excel: .xlsx, .xls, .xlsm, .xlsb, .xltx, .csv
- PowerPoint: .pptx, .ppt, .pptm, .potx
Áp dụng cơ chế sao lưu thông minh (Incremental Backup): Chỉ sao chép file mới hoặc đã thay đổi nội dung.
"""

import os
import sys
import re
import time
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Định nghĩa các phần mở rộng tài liệu hợp lệ
DOC_TYPES = {
    "Word": {".docx", ".doc", ".docm", ".dotx", ".dot"},
    "PDF": {".pdf"},
    "Excel": {".xlsx", ".xls", ".xlsm", ".xlsb", ".xltx", ".csv"},
    "PowerPoint": {".pptx", ".ppt", ".pptm", ".potx"},
}

ALL_DOC_EXTENSIONS = set()
for exts in DOC_TYPES.values():
    ALL_DOC_EXTENSIONS.update(exts)

# Các thư mục hệ thống / nguy hiểm cần loại bỏ khi sao lưu
EXCLUDED_FOLDERS = {
    ".usb_quarantine", "system volume information", "recycler", "$recycle.bin", ".trashes"
}

# Các định dạng thực thi nguy hiểm không bao giờ được sao lưu
DANGEROUS_EXTENSIONS = {
    ".exe", ".scr", ".vbs", ".js", ".bat", ".cmd", ".pif", ".hta", ".wsf", ".lnk"
}


def format_bytes(size_bytes: int) -> str:
    """Đổi kích thước bytes sang chuỗi hiển thị thân thiện."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    val = float(size_bytes)
    while val >= 1024.0 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    return f"{val:.1f} {units[idx]}"


def classify_document(filename: str) -> Optional[str]:
    """
    Xác định loại tài liệu (Word, PDF, Excel, PowerPoint).
    Trả về None nếu không phải tài liệu hợp lệ hoặc là file giả mạo nguy hiểm.
    """
    fname_lower = filename.lower()

    # Kiểm tra an toàn: nếu chứa đuôi kép kết thúc bằng file thực thi -> Bỏ qua
    for d_ext in DANGEROUS_EXTENSIONS:
        if fname_lower.endswith(d_ext):
            return None

    _, ext = os.path.splitext(fname_lower)
    if not ext:
        return None

    for doc_type, extensions in DOC_TYPES.items():
        if ext in extensions:
            return doc_type

    return None


class BackupReport:
    """Báo cáo chi tiết sau khi thực hiện sao lưu."""

    def __init__(self, drive: str, label: str, backup_target_dir: str):
        self.drive = drive
        self.label = label
        self.backup_target_dir = backup_target_dir
        self.copied_count = 0
        self.skipped_count = 0
        self.total_docs_found = 0
        self.copied_bytes = 0
        self.type_counts: Dict[str, int] = {"Word": 0, "PDF": 0, "Excel": 0, "PowerPoint": 0}
        self.start_time = time.time()
        self.end_time = 0.0
        self.is_success = True
        self.error_message = ""

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return max(0.01, end - self.start_time)

    @property
    def copied_bytes_str(self) -> str:
        return format_bytes(self.copied_bytes)

    def summary(self) -> str:
        breakdown = [f"{k}: {v}" for k, v in self.type_counts.items() if v > 0]
        breakdown_str = f" ({', '.join(breakdown)})" if breakdown else ""
        return (
            f"Đã sao lưu {self.copied_count} tài liệu mới{breakdown_str} "
            f"[{self.copied_bytes_str}], giữ nguyên {self.skipped_count} tệp cũ "
            f"trong {self.duration_seconds:.1f}s."
        )


class USBBackupManager:
    """Trình quản lý sao lưu tài liệu USB."""

    def __init__(self):
        pass

    def backup_drive(
        self,
        drive_path: str,
        label: str,
        backup_root_dir: str,
        max_depth: int = 5,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> BackupReport:
        """
        Quét và sao lưu các tệp Word, PDF, Excel, PowerPoint từ USB vào máy tính.
        Tạo thư mục con riêng biệt cho từng USB theo cấu trúc:
        {backup_root_dir}/{safe_label}_{drive_letter}/
        """
        clean_drive = drive_path.rstrip("\\/") + "\\"
        drive_letter = clean_drive[0].upper()

        # Tạo tên thư mục an toàn không chứa ký tự cấm của Windows
        safe_label = re.sub(r'[\/:*?"<>|]', "_", label).strip() or "USB"
        target_subfolder = f"{safe_label}_{drive_letter}"
        target_dir = os.path.join(backup_root_dir, target_subfolder)

        report = BackupReport(clean_drive, label, target_dir)

        if not os.path.exists(clean_drive):
            report.is_success = False
            report.error_message = f"Ổ đĩa {clean_drive} không tồn tại hoặc đã bị rút ra."
            return report

        try:
            os.makedirs(target_dir, exist_ok=True)

            for root, dirs, files in os.walk(clean_drive):
                # Kiểm tra loại trừ thư mục
                root_lower = root.lower()
                rel_path = os.path.relpath(root, clean_drive)
                depth = 0 if rel_path == "." else len(rel_path.split(os.sep))
                if depth > max_depth:
                    continue

                if any(ex_dir in root_lower for ex_dir in EXCLUDED_FOLDERS):
                    continue

                for fname in files:
                    doc_type = classify_document(fname)
                    if not doc_type:
                        continue

                    src_file = os.path.join(root, fname)
                    report.total_docs_found += 1

                    # Xác định đường dẫn tương đối để tái tạo cấu trúc thư mục
                    rel_file_path = os.path.relpath(src_file, clean_drive)
                    dest_file = os.path.join(target_dir, rel_file_path)

                    # Kiểm tra trùng lặp thông minh (Incremental Backup)
                    if self._should_copy(src_file, dest_file):
                        try:
                            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                            shutil.copy2(src_file, dest_file)  # copy2 giữ lại timestamp mtime
                            report.copied_count += 1
                            report.copied_bytes += os.path.getsize(src_file)
                            report.type_counts[doc_type] += 1
                        except Exception as copy_err:
                            print(f"[Backup Error] Lỗi sao chép {src_file}: {copy_err}")
                    else:
                        report.skipped_count += 1
                        report.type_counts[doc_type] += 1

                    if on_progress and (report.total_docs_found % 10 == 0):
                        on_progress(report.total_docs_found, fname)

        except Exception as e:
            report.is_success = False
            report.error_message = str(e)
            print(f"[Backup Error] Lỗi tiến trình sao lưu: {e}")

        report.end_time = time.time()
        return report

    def _should_copy(self, src_file: str, dest_file: str) -> bool:
        """
        Kiểm tra xem có cần sao chép tệp không:
        - Nếu file đích chưa có -> Cần sao chép
        - Nếu kích thước hoặc thời gian sửa đổi khác nhau -> Cần sao chép
        - Nếu kích thước và mtime hoàn toàn giống nhau -> Bỏ qua
        """
        if not os.path.exists(dest_file):
            return True

        try:
            src_stat = os.stat(src_file)
            dest_stat = os.stat(dest_file)

            if src_stat.st_size != dest_stat.st_size:
                return True

            # Cho phép chênh lệch tối đa 1.5 giây do sai số timestamp FAT32/NTFS
            if abs(src_stat.st_mtime - dest_stat.st_mtime) > 1.5:
                return True

            return False
        except Exception:
            return True


if __name__ == "__main__":
    print("USB Backup Manager loaded.")
    test_files = ["Report.docx", "Budget.xlsx", "Presentation.pptx", "Guide.pdf", "Trojan.pdf.exe", "Photo.jpg"]
    for f in test_files:
        print(f"{f} -> {classify_document(f)}")
