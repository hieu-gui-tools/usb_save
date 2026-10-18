"""
Module quản lý cấu hình và ghi nhớ cài đặt của ứng dụng USB Shield & Detector.
Lưu trữ thiết lập trong file config.json ở cùng thư mục ứng dụng.
"""

import os
import sys
import json
from typing import Dict, Any, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

CONFIG_FILE_NAME = "config.json"


def get_app_dir() -> str:
    """Trả về thư mục ứng dụng (hỗ trợ cả chạy mã nguồn và khi đóng gói file exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_default_backup_dir() -> str:
    """Trả về thư mục sao lưu mặc định trong Documents của người dùng."""
    user_docs = os.path.join(os.path.expanduser("~"), "Documents")
    backup_dir = os.path.join(user_docs, "USB_Backups")
    return os.path.abspath(backup_dir)


DEFAULT_CONFIG: Dict[str, Any] = {
    "notify_enabled": True,
    "cli_notify_enabled": True,
    "auto_scan_enabled": True,
    "auto_quarantine_enabled": True,
    "auto_backup_enabled": True,
    "backup_directory": get_default_backup_dir(),
}

TELEGRAM_KEYS = {
    "telegram_backup_enabled",
    "telegram_bot_token",
    "telegram_bot_id",
    "telegram_chat_id",
    "telegram_settle_delay",
    "bot_id",
    "bot_token",
    "chat_id",
    "id_bot",
    "id_chat",
    "token",
}


class ConfigManager:
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = get_app_dir()
        self.config_path = os.path.join(config_dir, CONFIG_FILE_NAME)
        self.config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> Dict[str, Any]:
        """Đọc cấu hình từ file config.json nếu tồn tại (loại bỏ mọi cấu hình Telegram)."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    has_telegram_keys = any(
                        k.startswith("telegram_") or k in TELEGRAM_KEYS for k in data
                    )
                    cleaned_data = {
                        k: v for k, v in data.items()
                        if not (k.startswith("telegram_") or k in TELEGRAM_KEYS)
                    }
                    self.config.update(cleaned_data)
                    # Nếu file cũ có chứa key cấu hình telegram, dọn dẹp và lưu đè lại
                    if has_telegram_keys:
                        self.save()
            except Exception as e:
                print(f"[ConfigManager Error] Không thể đọc {self.config_path}: {e}")
        else:
            # Tạo file cấu hình mặc định
            self.save()
        return self.config

    def save(self) -> bool:
        """Ghi cấu hình hiện tại ra file config.json (đảm bảo không lưu cấu hình telegram)."""
        try:
            data_to_save = {
                k: v for k, v in self.config.items()
                if not (k.startswith("telegram_") or k in TELEGRAM_KEYS)
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager Error] Không thể ghi {self.config_path}: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        if key.startswith("telegram_") or key in TELEGRAM_KEYS:
            return default
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key.startswith("telegram_") or key in TELEGRAM_KEYS:
            # Không lưu các cấu hình telegram vào config.json
            return
        self.config[key] = value
        self.save()



if __name__ == "__main__":
    cm = ConfigManager()
    print("Cấu hình hiện tại:", cm.config)
