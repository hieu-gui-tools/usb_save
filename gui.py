"""
Giao diện điều khiển USB Shield & Detector với Tkinter và khay hệ thống (System Tray).
Tích hợp trung tâm bảo vệ & sao lưu USB:
- Tự động nhận diện thiết bị USB cắm/rút trong thời gian thực
- Tự động quét và ngăn chặn mã độc / autorun.inf
- Tiêm phòng chống lây nhiễm USB (Immunize)
- Khôi phục file ẩn do virus shortcut (Unhide)
- Quản lý và khôi phục khu vực cách ly (Quarantine Vault)
- Tự động sao lưu tài liệu văn phòng (Word, PDF, Excel, PowerPoint) vào máy tính
- Tùy chỉnh thư mục lưu trữ và bật/tắt linh hoạt các tính năng
"""

import os
import sys
import time
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, Any, Optional, List
from PIL import Image, ImageDraw
import pystray

from config_manager import ConfigManager
from notifier import USBNotifier
from usb_detector import USBDetector, list_usb_drives
from usb_scanner import USBScanner, ScanResult, ThreatInfo
from usb_backup import USBBackupManager, BackupReport
from telegram_backup import TelegramBackupManager, TelegramUploader
from folder_watcher import FolderWatcher


if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def generate_usb_icon(size: int = 64) -> Image.Image:
    """Tạo biểu tượng USB sắc nét bằng Pillow."""
    image = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 64.0

    # Đầu kim loại USB
    draw.rounded_rectangle(
        [18 * scale, 8 * scale, 46 * scale, 26 * scale],
        radius=int(2 * scale),
        outline="#222222",
        fill="#D0D5DD",
        width=int(2 * scale),
    )
    draw.rectangle([22 * scale, 13 * scale, 28 * scale, 21 * scale], fill="#475467")
    draw.rectangle([36 * scale, 13 * scale, 42 * scale, 21 * scale], fill="#475467")

    # Thân USB
    draw.rounded_rectangle(
        [12 * scale, 24 * scale, 52 * scale, 58 * scale],
        radius=int(6 * scale),
        fill="#0284C7",
        outline="#0369A1",
        width=int(2 * scale),
    )
    # Đèn LED chỉ báo
    draw.ellipse([29 * scale, 34 * scale, 35 * scale, 40 * scale], fill="#22C55E")
    return image


class USBDetectorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("USB Shield & Backup - Bảo Vệ & Sao Lưu USB")
        self.root.geometry("880x700")
        self.root.minsize(800, 560)

        # Quản lý cấu hình
        self.config_mgr = ConfigManager()

        self.icon_image = generate_usb_icon(64)
        self.icon_photo = None
        try:
            from PIL import ImageTk
            self.icon_photo = ImageTk.PhotoImage(self.icon_image)
            self.root.iconphoto(False, self.icon_photo)
        except Exception:
            pass

        self.notifier = USBNotifier()
        self.scanner = USBScanner()
        self.backup_mgr = USBBackupManager()
        self.detector = USBDetector(
            on_connected=self._on_usb_connected_bg,
            on_disconnected=self._on_usb_disconnected_bg,
            poll_interval=1.0,
        )

        self.tray_icon: Optional[pystray.Icon] = None

        # Khởi tạo các biến tùy chọn từ cấu hình đã lưu
        self.notify_enabled = tk.BooleanVar(value=self.config_mgr.get("notify_enabled", True))
        self.auto_scan_enabled = tk.BooleanVar(value=self.config_mgr.get("auto_scan_enabled", True))
        self.auto_quarantine_enabled = tk.BooleanVar(value=self.config_mgr.get("auto_quarantine_enabled", True))
        self.auto_backup_enabled = tk.BooleanVar(value=self.config_mgr.get("auto_backup_enabled", True))
        self.backup_dir_var = tk.StringVar(value=self.config_mgr.get("backup_directory", ""))

        # Cấu hình Telegram Cloud Backup (chỉ lưu tạm trong RAM, không lưu vào config.json)
        self.telegram_backup_enabled = tk.BooleanVar(value=False)
        self.telegram_bot_token = ""
        self.telegram_chat_id = ""
        self.telegram_settle_delay = 2.5

        self.telegram_mgr = TelegramBackupManager(on_log=self._on_telegram_log)
        self.telegram_mgr.configure(
            bot_token=self.telegram_bot_token,
            chat_id=self.telegram_chat_id,
            enabled=self.telegram_backup_enabled.get(),
            settle_delay=self.telegram_settle_delay,
        )
        self.telegram_mgr.start()

        self.folder_watcher = FolderWatcher(
            watch_dir=self.backup_dir_var.get(),
            on_file_changed=self._on_watched_file_changed,
            on_log=self._on_telegram_log,
        )
        if self.telegram_backup_enabled.get():
            self.folder_watcher.start()


        self._setup_style()
        self._build_ui()
        self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self.detector.start()
        self._refresh_connected_list()
        self.log_message("🚀 Ứng dụng đã kích hoạt! Chế độ lá chắn và sao lưu tài liệu đang chạy...", "INFO")

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background="#F8FAFC")
        style.configure("Header.TFrame", background="#0F172A")
        style.configure("Header.TLabel", background="#0F172A", foreground="#FFFFFF", font=("Segoe UI", 13, "bold"))
        style.configure("Status.TLabel", background="#0F172A", foreground="#38BDF8", font=("Segoe UI", 9, "bold"))

        style.configure("TLabelframe", background="#F8FAFC", bordercolor="#CBD5E1")
        style.configure("TLabelframe.Label", background="#F8FAFC", foreground="#1E293B", font=("Segoe UI", 10, "bold"))

        style.configure("TButton", font=("Segoe UI", 9), padding=5)
        style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=26)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#E2E8F0")

    def _build_ui(self):
        self.root.configure(bg="#F8FAFC")

        # Header bar
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(16, 12))
        header.pack(fill=tk.X)

        title_label = ttk.Label(header, text="🛡️ Lá Chắn Bảo Vệ & Sao Lưu Tài Liệu USB", style="Header.TLabel")
        title_label.pack(side=tk.LEFT)

        self.status_label = ttk.Label(header, text="● Hệ thống đang bảo vệ & sẵn sàng sao lưu", style="Status.TLabel")
        self.status_label.pack(side=tk.RIGHT)

        # Main content
        content = ttk.Frame(self.root, padding=12)
        content.pack(fill=tk.BOTH, expand=True)

        # --- Section 1: USB đang kết nối ---
        devices_frame = ttk.LabelFrame(content, text=" 💾 Thiết bị USB đang kết nối ", padding=10)
        devices_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))

        columns = ("drive", "label", "filesystem", "free", "total", "device")
        self.tree = ttk.Treeview(devices_frame, columns=columns, show="headings", height=3)
        self.tree.heading("drive", text="Ổ đĩa")
        self.tree.heading("label", text="Tên nhãn (Label)")
        self.tree.heading("filesystem", text="Định dạng")
        self.tree.heading("free", text="Dung lượng trống")
        self.tree.heading("total", text="Tổng dung lượng")
        self.tree.heading("device", text="Dòng thiết bị")

        self.tree.column("drive", width=65, anchor="center")
        self.tree.column("label", width=140, anchor="w")
        self.tree.column("filesystem", width=80, anchor="center")
        self.tree.column("free", width=120, anchor="e")
        self.tree.column("total", width=120, anchor="e")
        self.tree.column("device", width=200, anchor="w")

        tree_scroll = ttk.Scrollbar(devices_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Thanh công cụ bảo mật USB
        sec_toolbar = ttk.Frame(content)
        sec_toolbar.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(sec_toolbar, text="🛡️ Quét USB này", command=self.scan_selected_drive).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sec_toolbar, text="💉 Tiêm phòng Autorun", command=self.immunize_selected_drive).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sec_toolbar, text="👁️ Hiện file bị ẩn", command=self.unhide_selected_drive).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sec_toolbar, text="📦 Xem file cách ly", command=self.open_quarantine_manager).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sec_toolbar, text="📂 Mở Explorer", command=self.open_selected_drive).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sec_toolbar, text="🔄 Quét lại", command=self._refresh_connected_list).pack(side=tk.LEFT)

        # --- Section 2: Sao lưu tài liệu văn phòng ---
        backup_frame = ttk.LabelFrame(content, text=" 📂 Sao lưu tài liệu (Word, PDF, Excel, PowerPoint) ", padding=10)
        backup_frame.pack(fill=tk.X, pady=(0, 10))

        bk_row1 = ttk.Frame(backup_frame)
        bk_row1.pack(fill=tk.X, pady=(0, 6))

        backup_chk = ttk.Checkbutton(
            bk_row1,
            text="Bật tự động sao lưu tài liệu khi cắm USB",
            variable=self.auto_backup_enabled,
            command=self._on_settings_changed,
        )
        backup_chk.pack(side=tk.LEFT, padx=(0, 12))

        backup_now_btn = ttk.Button(bk_row1, text="💾 Sao lưu ổ này ngay", command=self.backup_selected_drive)
        backup_now_btn.pack(side=tk.LEFT, padx=(0, 6))

        open_bk_btn = ttk.Button(bk_row1, text="📂 Mở thư mục sao lưu", command=self.open_backup_directory)
        open_bk_btn.pack(side=tk.LEFT, padx=(0, 6))

        change_bk_btn = ttk.Button(bk_row1, text="📁 Chọn thư mục lưu...", command=self.change_backup_directory)
        change_bk_btn.pack(side=tk.LEFT)

        # Hiển thị đường dẫn thư mục lưu
        bk_row2 = ttk.Frame(backup_frame)
        bk_row2.pack(fill=tk.X)

        ttk.Label(bk_row2, text="📍 Lưu tại: ", font=("Segoe UI", 9, "bold"), foreground="#475467").pack(side=tk.LEFT)
        self.path_label = ttk.Label(bk_row2, textvariable=self.backup_dir_var, font=("Consolas", 9), foreground="#0284C7")
        self.path_label.pack(side=tk.LEFT)

        # --- Section: Sao lưu đám mây Telegram ---
        tg_frame = ttk.LabelFrame(content, text=" ☁️ Sao lưu đám mây Telegram Group (Tự động tải file mới/sửa) ", padding=10)
        tg_frame.pack(fill=tk.X, pady=(0, 10))

        tg_row1 = ttk.Frame(tg_frame)
        tg_row1.pack(fill=tk.X)

        tg_chk = ttk.Checkbutton(
            tg_row1,
            text="Tự động đồng bộ file lên nhóm Telegram",
            variable=self.telegram_backup_enabled,
            command=self._toggle_telegram_backup,
        )
        tg_chk.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(tg_row1, text="⚙️ Cấu hình Bot & Nhóm...", command=self.open_telegram_config_dialog).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tg_row1, text="📜 Lịch sử Upload (SQLite)", command=self.open_telegram_history_dialog).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tg_row1, text="🔄 Thử lại file lỗi", command=self.retry_telegram_failed).pack(side=tk.LEFT)

        # Hàng tùy chọn bảo vệ tự động
        opt_frame = ttk.Frame(content)
        opt_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Checkbutton(
            opt_frame,
            text="Tự động quét khi cắm USB",
            variable=self.auto_scan_enabled,
            command=self._on_settings_changed,
        ).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Checkbutton(
            opt_frame,
            text="Tự động cách ly file độc hại / autorun",
            variable=self.auto_quarantine_enabled,
            command=self._on_settings_changed,
        ).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Checkbutton(
            opt_frame,
            text="Thông báo Windows Toast",
            variable=self.notify_enabled,
            command=self._on_settings_changed,
        ).pack(side=tk.LEFT)

        # --- Section 3: Nhật ký hoạt động ---
        log_frame = ttk.LabelFrame(content, text=" 📜 Nhật ký hoạt động, bảo mật & sao lưu ", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#FFFFFF",
            fg="#1E293B",
            relief="solid",
            borderwidth=1,
            height=8
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_config("INFO", foreground="#0284C7")
        self.log_text.tag_config("CONNECT", foreground="#059669", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("DISCONNECT", foreground="#64748B")
        self.log_text.tag_config("CLEAN", foreground="#16A34A", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("BACKUP", foreground="#7C3AED", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("THREAT", foreground="#DC2626", font=("Consolas", 9, "bold"), background="#FEE2E2")
        self.log_text.tag_config("WARN", foreground="#D97706")
        self.log_text.tag_config("TELEGRAM", foreground="#0284C7", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("TELEGRAM_SUCCESS", foreground="#059669", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("TELEGRAM_WARN", foreground="#D97706", font=("Consolas", 9, "bold"))


        # Bottom Bar
        bottom_bar = ttk.Frame(self.root, padding=(12, 8))
        bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)

        test_btn = ttk.Button(bottom_bar, text="🔔 Thử thông báo Toast", command=self.test_notification)
        test_btn.pack(side=tk.LEFT, padx=(0, 6))

        clear_log_btn = ttk.Button(bottom_bar, text="🧹 Xóa nhật ký", command=self.clear_log)
        clear_log_btn.pack(side=tk.LEFT, padx=(0, 6))

        exit_btn = ttk.Button(bottom_bar, text="❌ Thoát hoàn toàn", command=self.quit_app)
        exit_btn.pack(side=tk.RIGHT)

        tray_btn = ttk.Button(bottom_bar, text="📥 Thu nhỏ xuống Khay (Tray)", command=self.hide_to_tray)
        tray_btn.pack(side=tk.RIGHT, padx=6)

    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Mở giao diện", self.restore_from_tray, default=True),
            pystray.MenuItem("Kiểm tra thông báo", lambda icon, item: self.test_notification()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát", lambda icon, item: self.root.after(0, self.quit_app))
        )
        self.tray_icon = pystray.Icon("USBShield", self.icon_image, "USB Shield & Backup", menu)
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True, name="TrayThread")
        tray_thread.start()

    def _on_settings_changed(self):
        """Lưu lại cài đặt vào file cấu hình mỗi khi người dùng thay đổi."""
        self.config_mgr.set("notify_enabled", self.notify_enabled.get())
        self.config_mgr.set("auto_scan_enabled", self.auto_scan_enabled.get())
        self.config_mgr.set("auto_quarantine_enabled", self.auto_quarantine_enabled.get())
        self.config_mgr.set("auto_backup_enabled", self.auto_backup_enabled.get())
        self.config_mgr.set("backup_directory", self.backup_dir_var.get())

    def _on_telegram_log(self, message: str, tag: str = "TELEGRAM"):
        self.root.after(0, lambda: self.log_message(message, tag))

    def _on_watched_file_changed(self, abs_path: str, rel_path: str):
        if self.telegram_backup_enabled.get():
            self.telegram_mgr.enqueue_file(abs_path, rel_path)

    def _toggle_telegram_backup(self):
        enabled = self.telegram_backup_enabled.get()
        self.telegram_mgr.configure(
            bot_token=self.telegram_bot_token,
            chat_id=self.telegram_chat_id,
            enabled=enabled,
            settle_delay=self.telegram_settle_delay,
        )
        if enabled:
            if not self.telegram_bot_token or not self.telegram_chat_id:
                messagebox.showwarning(
                    "Cần cấu hình Telegram",
                    "Vui lòng nhấn nút '⚙️ Cấu hình Bot & Nhóm' để nhập Bot Token và Chat ID trước khi kích hoạt."
                )
            self.folder_watcher.start()
            self.log_message("☁️ Đã kích hoạt tính năng tự động sao lưu đám mây Telegram.", "TELEGRAM")
        else:
            self.folder_watcher.stop()
            self.log_message("⏸️ Đã tạm dừng tính năng sao lưu đám mây Telegram.", "INFO")
        self._on_settings_changed()

    def retry_telegram_failed(self):
        self.telegram_mgr.retry_failed_items()


    def hide_to_tray(self):
        self.root.withdraw()
        if self.notify_enabled.get():
            self.log_message("Ứng dụng đang chạy ngầm trong khay hệ thống.", "INFO")

    def restore_from_tray(self, icon=None, item=None):
        self.root.after(0, self._restore_ui)

    def _restore_ui(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def log_message(self, message: str, tag: str = "INFO"):
        timestamp = time.strftime("[%H:%M:%S]")
        formatted = f"{timestamp} {message}\n"
        self.log_text.insert(tk.END, formatted, tag)
        self.log_text.see(tk.END)

    def _refresh_connected_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        current_usbs = self.detector.get_current_usbs()
        for letter, info in current_usbs.items():
            device_str = f"{info.get('vendor', '')} {info.get('product', '')}".strip() or "USB Storage"
            self.tree.insert(
                "",
                tk.END,
                iid=info["drive"],
                values=(
                    info["drive"],
                    info.get("label", "USB Drive"),
                    info.get("file_system", "N/A"),
                    info.get("free_space_str", "N/A"),
                    info.get("total_space_str", "N/A"),
                    device_str,
                ),
            )

    def _get_selected_drive(self) -> Optional[str]:
        selected = self.tree.selection()
        if selected:
            return selected[0]
        current = self.detector.get_current_usbs()
        if len(current) == 1:
            return list(current.values())[0]["drive"]
        messagebox.showinfo("Chọn ổ đĩa", "Vui lòng chọn 1 ổ đĩa USB trong danh sách phía trên.")
        return None

    def _on_usb_connected_bg(self, usb_info: Dict[str, Any]):
        self.root.after(0, lambda: self._handle_usb_connected(usb_info))

    def _handle_usb_connected(self, usb_info: Dict[str, Any]):
        drive = usb_info.get("drive", "")
        label = usb_info.get("label", "USB Drive")
        free = usb_info.get("free_space_str", "N/A")
        total = usb_info.get("total_space_str", "N/A")

        self.log_message(
            f"🔌 CẮM USB MỚI: Ổ {drive} ({label}) - Trống {free} / {total} [{usb_info.get('file_system')}]",
            "CONNECT"
        )
        self._refresh_connected_list()

        # Phát thông báo cắm USB
        if self.notify_enabled.get():
            self.notifier.notify_connected(usb_info)

        # Chạy quy trình bảo vệ và sao lưu
        threading.Thread(
            target=self._process_usb_pipeline,
            args=(drive, label),
            daemon=True,
        ).start()

    def _process_usb_pipeline(self, drive: str, label: str):
        """
        Quy trình xử lý hoàn chỉnh khi cắm USB:
        1. Quét bảo mật (nếu bật).
        2. Sau khi quét an toàn, tự động sao lưu tài liệu (nếu bật).
        """
        if self.auto_scan_enabled.get():
            self.root.after(0, lambda: self.log_message(f"🔍 Bắt đầu quét bảo mật trên ổ {drive} ({label})...", "INFO"))
            result = self.scanner.scan_drive(drive, auto_quarantine=self.auto_quarantine_enabled.get())

            def update_scan_ui():
                if result.is_safe:
                    self.log_message(
                        f"✅ QUÉT HOÀN TẤT: Ổ {drive} an toàn. Đã kiểm tra {result.scanned_files_count} tệp tin.",
                        "CLEAN"
                    )
                else:
                    self.log_message(
                        f"🚨 CẢNH BÁO NGUY HIỂM: Phát hiện {result.threat_count} mối đe dọa trên ổ {drive}!",
                        "THREAT"
                    )
                    for threat in result.threats:
                        status_text = "ĐÃ CÁCH LY" if threat.quarantined else "CHƯA CÁCH LY"
                        self.log_message(
                            f"  ❌ [{threat.threat_type}] {threat.filename} -> {threat.description} ({status_text})",
                            "THREAT"
                        )
                    if self.notify_enabled.get():
                        self.notifier.notify_threat_detected(drive, label, result.threats)

            self.root.after(0, update_scan_ui)

        # Tiến hành sao lưu tài liệu nếu tùy chọn được bật
        if self.auto_backup_enabled.get():
            self._execute_backup(drive, label)

    def _execute_backup(self, drive: str, label: str):
        """Tiến hành sao lưu tài liệu Word, PDF, Excel, PowerPoint."""
        backup_root = self.backup_dir_var.get()
        self.root.after(0, lambda: self.log_message(
            f"💾 Bắt đầu sao lưu tài liệu văn phòng (Word, PDF, Excel, PowerPoint) từ ổ {drive}...",
            "INFO"
        ))

        report = self.backup_mgr.backup_drive(drive, label, backup_root)

        def update_backup_ui():
            if not report.is_success:
                self.log_message(f"⚠️ Lỗi sao lưu ổ {drive}: {report.error_message}", "WARN")
                return

            if report.total_docs_found == 0:
                self.log_message(f"ℹ️ Không có tài liệu Word, PDF, Excel, PowerPoint nào trên ổ {drive}.", "INFO")
                return

            # Tổng kết sao lưu
            self.log_message(f"✅ {report.summary()}", "BACKUP")

            if report.copied_count > 0 and self.notify_enabled.get():
                self.notifier.notify_backup_completed(
                    drive=drive,
                    label=label,
                    copied_count=report.copied_count,
                    total_count=report.total_docs_found,
                    bytes_str=report.copied_bytes_str,
                    target_dir=report.backup_target_dir,
                )

            if report.copied_count > 0 and self.telegram_backup_enabled.get():
                self.folder_watcher.scan_now()

        self.root.after(0, update_backup_ui)


    def _on_usb_disconnected_bg(self, usb_info: Dict[str, Any]):
        self.root.after(0, lambda: self._handle_usb_disconnected(usb_info))

    def _handle_usb_disconnected(self, usb_info: Dict[str, Any]):
        drive = usb_info.get("drive", "")
        label = usb_info.get("label", "USB Drive")

        self.log_message(
            f"⚠️ RÚT USB: Thiết bị {drive} ({label}) đã bị ngắt kết nối.",
            "DISCONNECT"
        )
        self._refresh_connected_list()

        if self.notify_enabled.get():
            self.notifier.notify_disconnected(usb_info)

    def scan_selected_drive(self):
        drive = self._get_selected_drive()
        if not drive:
            return
        label = drive
        usbs = self.detector.get_current_usbs()
        clean_letter = drive.rstrip(":\\/").upper()
        if clean_letter in usbs:
            label = usbs[clean_letter].get("label", drive)

        threading.Thread(
            target=self._process_usb_pipeline,
            args=(drive, label),
            daemon=True,
        ).start()

    def backup_selected_drive(self):
        """Thực hiện sao lưu thủ công cho ổ đĩa đang chọn."""
        drive = self._get_selected_drive()
        if not drive:
            return
        label = drive
        usbs = self.detector.get_current_usbs()
        clean_letter = drive.rstrip(":\\/").upper()
        if clean_letter in usbs:
            label = usbs[clean_letter].get("label", drive)

        threading.Thread(
            target=self._execute_backup,
            args=(drive, label),
            daemon=True,
        ).start()

    def open_backup_directory(self):
        """Mở thư mục sao lưu trên máy tính trong File Explorer."""
        b_dir = self.backup_dir_var.get()
        try:
            os.makedirs(b_dir, exist_ok=True)
            os.startfile(b_dir)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể mở thư mục sao lưu: {e}")

    def change_backup_directory(self):
        """Mở hộp thoại cho người dùng chọn thư mục sao lưu mong muốn."""
        current_dir = self.backup_dir_var.get()
        chosen = filedialog.askdirectory(
            title="Chọn thư mục lưu trữ tài liệu sao lưu",
            initialdir=current_dir if os.path.isdir(current_dir) else None,
        )
        if chosen:
            chosen_abs = os.path.abspath(chosen)
            self.backup_dir_var.set(chosen_abs)
            self.folder_watcher.set_watch_dir(chosen_abs)
            self._on_settings_changed()
            self.log_message(f"📁 Đã thay đổi thư mục sao lưu thành: {chosen_abs}", "INFO")


    def immunize_selected_drive(self):
        drive = self._get_selected_drive()
        if not drive:
            return
        success, msg = self.scanner.immunize_drive(drive)
        if success:
            self.log_message(f"💉 [Tiêm phòng {drive}]: {msg}", "CLEAN")
            messagebox.showinfo("Tiêm phòng USB", msg)
        else:
            self.log_message(f"⚠️ [Lỗi tiêm phòng {drive}]: {msg}", "WARN")
            messagebox.showwarning("Cảnh báo", msg)

    def unhide_selected_drive(self):
        drive = self._get_selected_drive()
        if not drive:
            return
        self.log_message(f"👁️ Đang phục hồi các file bị ẩn trên ổ {drive}...", "INFO")

        def run_unhide():
            success, msg = self.scanner.unhide_files(drive)
            def done():
                if success:
                    self.log_message(f"✅ {msg}", "CLEAN")
                    messagebox.showinfo("Khôi phục file ẩn", msg)
                else:
                    self.log_message(f"⚠️ {msg}", "WARN")
                    messagebox.showwarning("Lỗi", msg)
            self.root.after(0, done)

        threading.Thread(target=run_unhide, daemon=True).start()

    def open_quarantine_manager(self):
        drive = self._get_selected_drive()
        if not drive:
            return

        quarantine_window = tk.Toplevel(self.root)
        quarantine_window.title(f"📦 Quản lý Cách ly - Ổ {drive}")
        quarantine_window.geometry("640x360")
        quarantine_window.transient(self.root)

        q_frame = ttk.Frame(quarantine_window, padding=12)
        q_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            q_frame,
            text=f"Danh sách tệp tin đang bị vô hiệu hóa an toàn trên {drive}",
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(0, 8))

        cols = ("filename", "type", "date", "path")
        tree = ttk.Treeview(q_frame, columns=cols, show="headings", height=8)
        tree.heading("filename", text="Tên file")
        tree.heading("type", text="Loại nguy cơ")
        tree.heading("date", text="Thời điểm cách ly")
        tree.heading("path", text="Đường dẫn gốc")

        tree.column("filename", width=140)
        tree.column("type", width=110, anchor="center")
        tree.column("date", width=130, anchor="center")
        tree.column("path", width=200)

        tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        items = self.scanner.list_quarantined_files(drive)
        item_map = {}
        for idx, it in enumerate(items):
            iid = str(idx)
            item_map[iid] = it
            tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    it.get("filename", ""),
                    it.get("threat_type", ""),
                    it.get("quarantine_time", ""),
                    it.get("original_path", ""),
                )
            )

        btn_box = ttk.Frame(q_frame)
        btn_box.pack(fill=tk.X)

        def restore_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Thông báo", "Vui lòng chọn 1 tệp tin để khôi phục.")
                return
            meta = item_map[sel[0]]
            if messagebox.askyesno("Xác nhận", f"Bạn có chắc muốn khôi phục tệp '{meta['filename']}' về vị trí ban đầu?"):
                ok = self.scanner.restore_quarantined_file(meta)
                if ok:
                    messagebox.showinfo("Thành công", f"Đã khôi phục tệp về: {meta['original_path']}")
                    tree.delete(sel[0])
                else:
                    messagebox.showerror("Lỗi", "Không thể khôi phục tệp.")

        def delete_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Thông báo", "Vui lòng chọn 1 tệp tin để xóa vĩnh viễn.")
                return
            meta = item_map[sel[0]]
            if messagebox.askyesno("Xóa vĩnh viễn", f"Cảnh báo: Tệp '{meta['filename']}' sẽ bị xóa hoàn toàn khỏi USB!"):
                q_file = meta.get("quarantine_file", "")
                m_file = q_file + ".meta"
                try:
                    if os.path.exists(q_file):
                        os.remove(q_file)
                    if os.path.exists(m_file):
                        os.remove(m_file)
                    tree.delete(sel[0])
                    messagebox.showinfo("Đã xóa", "Đã xóa vĩnh viễn tệp độc hại.")
                except Exception as e:
                    messagebox.showerror("Lỗi", f"Không thể xóa: {e}")

        ttk.Button(btn_box, text="🔄 Khôi phục tệp này", command=restore_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_box, text="🗑️ Xóa vĩnh viễn", command=delete_selected).pack(side=tk.LEFT)
        ttk.Button(btn_box, text="Đóng", command=quarantine_window.destroy).pack(side=tk.RIGHT)

    def open_telegram_config_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("⚙️ Cấu hình Telegram Cloud Backup")
        dialog.geometry("560x410")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Cấu hình gửi file lên nhóm Telegram",
            font=("Segoe UI", 11, "bold"),
            foreground="#0F172A",
        ).pack(anchor="w", pady=(0, 2))

        ttk.Label(
            frame,
            text="🔒 Cấu hình Telegram chỉ lưu tạm trong bộ nhớ RAM khi chạy, không lưu vào config.json.",
            font=("Segoe UI", 8, "italic"),
            foreground="#64748B",
        ).pack(anchor="w", pady=(0, 8))

        def mask_secret(secret: str, start: int = 4, end: int = 4) -> str:
            s = str(secret or "").strip()
            if not s:
                return "(chưa cấu hình)"
            if len(s) <= start + end:
                return s[:start] + "•••"
            masked_len = min(20, max(6, len(s) - (start + end)))
            return s[:start] + ("•" * masked_len) + s[-end:]

        # Bot Token (bảo vệ dạng mật khẩu - không bao giờ hiển thị toàn bộ)
        token_container = ttk.Frame(frame)
        token_container.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(token_container, text="Bot Token (tạo từ @BotFather):", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        token_row = ttk.Frame(token_container)
        token_row.pack(fill=tk.X, pady=(2, 2))
        token_entry = ttk.Entry(token_row, font=("Consolas", 9), show="•")
        token_entry.insert(0, self.telegram_bot_token)
        token_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        token_preview_var = tk.StringVar(value="")
        token_preview_label = ttk.Label(token_container, textvariable=token_preview_var, font=("Consolas", 8), foreground="#0369A1")

        token_toggle_btn = ttk.Button(token_row, text="👁️", width=4)
        def toggle_token():
            if token_preview_var.get() == "":
                val = token_entry.get().strip()
                token_preview_var.set(f"🔒 Xem an toàn (đã che giấu): {mask_secret(val, 4, 4)}")
                token_preview_label.pack(anchor="w", pady=(2, 2))
                token_toggle_btn.configure(text="🔒")
            else:
                token_preview_var.set("")
                token_preview_label.pack_forget()
                token_toggle_btn.configure(text="👁️")
        token_toggle_btn.configure(command=toggle_token)
        token_toggle_btn.pack(side=tk.RIGHT)

        # Chat ID (bảo vệ dạng mật khẩu - không bao giờ hiển thị toàn bộ)
        chat_container = ttk.Frame(frame)
        chat_container.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(chat_container, text="Chat ID / Group ID (Ví dụ: -100123456789):", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        chat_row = ttk.Frame(chat_container)
        chat_row.pack(fill=tk.X, pady=(2, 2))
        chat_entry = ttk.Entry(chat_row, font=("Consolas", 9), show="•")
        chat_entry.insert(0, self.telegram_chat_id)
        chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        chat_preview_var = tk.StringVar(value="")
        chat_preview_label = ttk.Label(chat_container, textvariable=chat_preview_var, font=("Consolas", 8), foreground="#0369A1")

        chat_toggle_btn = ttk.Button(chat_row, text="👁️", width=4)
        def toggle_chat():
            if chat_preview_var.get() == "":
                val = chat_entry.get().strip()
                chat_preview_var.set(f"🔒 Xem an toàn (đã che giấu): {mask_secret(val, 4, 4)}")
                chat_preview_label.pack(anchor="w", pady=(2, 2))
                chat_toggle_btn.configure(text="🔒")
            else:
                chat_preview_var.set("")
                chat_preview_label.pack_forget()
                chat_toggle_btn.configure(text="👁️")
        chat_toggle_btn.configure(command=toggle_chat)
        chat_toggle_btn.pack(side=tk.RIGHT)




        # Settle delay
        delay_frame = ttk.Frame(frame)
        delay_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(delay_frame, text="Thời gian chờ file copy/ghi xong trước khi upload (giây):").pack(side=tk.LEFT)
        delay_spin = ttk.Spinbox(delay_frame, from_=1, to=30, width=5)
        delay_spin.set(str(int(self.telegram_settle_delay)))
        delay_spin.pack(side=tk.LEFT, padx=(8, 0))

        # Test connection result label
        test_status_var = tk.StringVar(value="")
        test_status_label = ttk.Label(frame, textvariable=test_status_var, wraplength=500, font=("Segoe UI", 9), foreground="#0284C7")
        test_status_label.pack(fill=tk.X, pady=(0, 10))

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM)

        def do_test():
            token = token_entry.get().strip()
            chat = chat_entry.get().strip()
            if not token or not chat:
                messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập đầy đủ Bot Token và Chat ID.")
                return
            test_status_var.set("⏳ Đang kiểm tra kết nối với máy chủ Telegram...")
            dialog.update_idletasks()

            def run_test():
                ok, msg = TelegramUploader.test_connection(token, chat)
                def on_done():
                    test_status_var.set(msg)
                    if ok:
                        messagebox.showinfo("Thành công", msg)
                    else:
                        messagebox.showwarning("Thất bại", msg)
                self.root.after(0, on_done)

            threading.Thread(target=run_test, daemon=True).start()

        def do_save():
            token = token_entry.get().strip()
            chat = chat_entry.get().strip()
            try:
                delay = float(delay_spin.get())
            except ValueError:
                delay = 2.5

            self.telegram_bot_token = token
            self.telegram_chat_id = chat
            self.telegram_settle_delay = delay
            self.telegram_mgr.configure(
                bot_token=token,
                chat_id=chat,
                enabled=self.telegram_backup_enabled.get(),
                settle_delay=delay,
            )
            self.log_message("⚙️ Đã áp dụng cấu hình Telegram thành công (chỉ lưu trong RAM)!", "INFO")
            dialog.destroy()

        ttk.Button(btn_box, text="🔔 Kiểm tra kết nối", command=do_test).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_box, text="💾 Áp dụng", style="Primary.TButton", command=do_save).pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="Hủy", command=dialog.destroy).pack(side=tk.RIGHT, padx=6)

    def open_telegram_history_dialog(self):
        hist_window = tk.Toplevel(self.root)
        hist_window.title("📜 Lịch sử Upload Telegram (SQLite)")
        hist_window.geometry("820x460")
        hist_window.transient(self.root)

        h_frame = ttk.Frame(hist_window, padding=12)
        h_frame.pack(fill=tk.BOTH, expand=True)

        header_row = ttk.Frame(h_frame)
        header_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            header_row,
            text="Lịch sử đồng bộ tệp tin lên Telegram Group (Lưu trong SQLite)",
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT)

        cols = ("id", "rel_path", "size", "status", "retries", "msg_id", "updated_at")
        tree = ttk.Treeview(h_frame, columns=cols, show="headings", height=12)
        tree.heading("id", text="ID")
        tree.heading("rel_path", text="Đường dẫn tệp")
        tree.heading("size", text="Kích thước")
        tree.heading("status", text="Trạng thái")
        tree.heading("retries", text="Lần thử")
        tree.heading("msg_id", text="Telegram Msg ID")
        tree.heading("updated_at", text="Thời điểm")

        tree.column("id", width=40, anchor="center")
        tree.column("rel_path", width=280, anchor="w")
        tree.column("size", width=80, anchor="e")
        tree.column("status", width=90, anchor="center")
        tree.column("retries", width=60, anchor="center")
        tree.column("msg_id", width=120, anchor="center")
        tree.column("updated_at", width=140, anchor="center")

        tree_scroll = ttk.Scrollbar(h_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def load_data():
            for it in tree.get_children():
                tree.delete(it)
            items = self.telegram_mgr.db.get_recent_history(limit=200)
            for r in items:
                size_b = r["file_size"]
                size_mb = size_b / (1024 * 1024)
                s_str = f"{size_mb:.1f} MB" if size_mb >= 1.0 else f"{size_b / 1024:.0f} KB"
                tree.insert(
                    "",
                    tk.END,
                    iid=str(r["id"]),
                    values=(
                        r["id"],
                        r["rel_path"],
                        s_str,
                        r["status"],
                        r["retry_count"],
                        r["telegram_message_id"] or "-",
                        r["updated_at"],
                    ),
                )

        load_data()

        b_box = ttk.Frame(hist_window, padding=(12, 8))
        b_box.pack(fill=tk.X, side=tk.BOTTOM)

        def do_retry():
            self.telegram_mgr.retry_failed_items()
            messagebox.showinfo("Thử lại", "Đã đưa các file lỗi hoặc chờ vào lại hàng đợi upload.")
            load_data()

        def do_clear():
            if messagebox.askyesno("Xác nhận", "Bạn có chắc chắn muốn xóa toàn bộ lịch sử upload trong SQLite?"):
                self.telegram_mgr.db.clear_all_history()
                load_data()

        ttk.Button(b_box, text="🔄 Thử lại các file lỗi/chờ", command=do_retry).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(b_box, text="🔄 Làm mới", command=load_data).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(b_box, text="🧹 Xóa toàn bộ lịch sử", command=do_clear).pack(side=tk.LEFT)
        ttk.Button(b_box, text="Đóng", command=hist_window.destroy).pack(side=tk.RIGHT)

    def open_selected_drive(self):
        drive_path = self._get_selected_drive()
        if not drive_path:
            return
        try:
            os.startfile(drive_path)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể mở ổ đĩa {drive_path}: {e}")

    def test_notification(self):
        self.log_message("Đang gửi thông báo thử nghiệm Windows Toast...", "INFO")
        success = self.notifier.notify_test()
        if success:
            self.log_message("Thông báo thử nghiệm đã phát thành công!", "INFO")
        else:
            self.log_message("Gửi thông báo thất bại, vui lòng kiểm tra cài đặt thông báo Windows.", "WARN")

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def quit_app(self):
        self.detector.stop()
        self.folder_watcher.stop()
        self.telegram_mgr.stop()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()



def run_app():
    root = tk.Tk()
    app = USBDetectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_app()
