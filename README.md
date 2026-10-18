# 🛡️ USB Shield & Backup (Windows)

Ứng dụng Python bảo vệ và quản lý thiết bị USB toàn diện trên Windows:
1. **Tự động nhận diện thiết bị USB** cắm/rút trong thời gian thực.
2. **Lá chắn bảo mật quét & ngăn chặn mã độc**: Tự động vô hiệu hóa `autorun.inf`, Shortcut Virus (`.lnk`), file ngụy trang đuôi kép (`*.pdf.exe`), kịch bản độc hại (`.vbs`, `.js`, `.wsf`, `.scr`).
3. **Tự động sao lưu tài liệu văn phòng vào máy tính**: Lọc và sao chép an toàn các tệp Word, PDF, Excel, PowerPoint vào thư mục chỉ định, có công tắc bật/tắt linh hoạt.
4. **Cơ chế sao lưu thông minh (Incremental Backup)**: Chỉ sao chép file mới hoặc đã chỉnh sửa, giữ nguyên cấu trúc thư mục USB và tránh sao chép trùng lặp.
5. **Cách ly an toàn (Quarantine Vault)**: Vô hiệu hóa file độc hại vào khu vực an toàn và cho phép khôi phục khi cần.
6. **Tiêm phòng USB (Immunization)** & **Khôi phục file ẩn (Unhide)**.
7. **Thông báo Windows Toast native** & Khay hệ thống (System Tray).

---

## ✨ Tính năng chi tiết

### 1. 📂 Tự động sao lưu tài liệu văn phòng (Word, PDF, Excel, PowerPoint)
- **Định dạng tài liệu được hỗ trợ**:
  - **Word**: `.docx`, `.doc`, `.docm`, `.dotx`, `.dot`
  - **PDF**: `.pdf`
  - **Excel**: `.xlsx`, `.xls`, `.xlsm`, `.xlsb`, `.xltx`, `.csv`
  - **PowerPoint**: `.pptx`, `.ppt`, `.pptm`, `.potx`
- **Bộ lọc an toàn**: Loại bỏ hoàn toàn các file thực thi, file đuôi kép giả mạo (`*.pdf.exe`), file trong thư mục cách ly `.usb_quarantine`, và các tệp không phải tài liệu (nhạc, video, ảnh).
- **Sao lưu thông minh**: So sánh ngày giờ (mtime) và kích thước tệp, chỉ sao chép các tài liệu mới hoặc có thay đổi nội dung, không copy lại file cũ.
- **Tùy chỉnh linh hoạt**:
  - Checkbox bật/tắt tự động sao lưu trực tiếp trong giao diện app.
  - Nút **"💾 Sao lưu ổ này ngay"** để thực hiện sao lưu thủ công bất kỳ lúc nào.
  - Nút **"📁 Chọn thư mục lưu..."** cho phép chọn bất kỳ thư mục nào trên ổ cứng máy tính.
  - Nút **"📂 Mở thư mục sao lưu"** mở nhanh thư mục trong File Explorer.
  - Tự động lưu cấu hình (file `config.json`) ghi nhớ thiết lập sau mỗi lần tắt/mở app.

### 2. 🔍 Quét & Ngăn chặn mã độc trong thời gian thực
- **Vô hiệu hóa `autorun.inf`**: Kiểm tra thư mục gốc USB, nhận diện lệnh khởi chạy âm thầm (ví dụ `open=malware.exe`) và lập tức cách ly.
- **Phát hiện Shortcut Virus**: Phân tích nội dung shortcut `.lnk` chứa câu lệnh ngầm độc hại (`powershell`, `cmd`, `wscript`, `mshta`, `rundll32`, `certutil`...).
- **Chặn file đuôi kép**: Bắt giữ các tệp ngụy trang như `BaoCao.pdf.exe`, `DuLieu.xlsx.scr`.
- **Khu vực cách ly an toàn (Quarantine Vault)**: Vô hiệu hóa và đổi đuôi sang `.quarantine`, hỗ trợ khôi phục file và xóa vĩnh viễn.

### 3. 💉 Tiêm phòng USB & 👁️ Hiện file bị ẩn
- **Tiêm phòng**: Tạo thư mục khóa `autorun.inf` có thuộc tính bảo vệ để chống virus USB lây nhiễm trong tương lai.
- **Hiện file bị ẩn**: Gỡ thuộc tính siêu ẩn do virus shortcut gây ra, lấy lại toàn bộ tài liệu gốc.

### 4. 🔔 Thông báo Windows Toast
- Báo khi cắm/rút USB.
- Cảnh báo đỏ khi phát hiện mã độc.
- Thông báo khi sao lưu hoàn tất (số lượng file, dung lượng, nút bấm mở nhanh thư mục lưu).

---

### 5. ☁️ Tự động đồng bộ & Sao lưu đám mây Telegram Group (Cloud Backup)
Tính năng bảo vệ dữ liệu tối thượng: Giúp bạn không bao giờ lo mất tài liệu ngay cả khi laptop bị hỏng, mất cắp hoặc hỏng ổ cứng.
- **Theo dõi thư mục thời gian thực (Folder Watcher)**:
  - Tự động giám sát toàn bộ thư mục lưu trữ và tất cả thư mục con (subfolders đệ quy).
  - Tự động nhận diện file mới được thêm vào hoặc file bị chỉnh sửa nội dung.
- **Chờ hoàn tất copy/ghi (Settle / Debounce)**:
  - Không upload vội vã khi file vừa xuất hiện để tránh đọc file dở dang khi Windows/Word/Excel đang ghi hoặc copy.
  - Tự động kiểm tra tính ổn định (size + mtime không đổi qua khoảng thời gian cấu hình và không bị file lock) rồi mới tiến hành upload.
- **Chống upload trùng lặp tuyệt đối (Deduplication)**:
  - Tính toán mã băm SHA-256 của nội dung tệp.
  - So khớp với lịch sử trong SQLite: Nếu file đã từng được tải lên thành công và nội dung không đổi, hệ thống sẽ bỏ qua ngay lập tức.
- **Cơ sở dữ liệu SQLite lưu vết lịch sử (`telegram_backup.db`)**:
  - Ghi nhận chi tiết: Đường dẫn tương đối, mã hash SHA-256, dung lượng, thời gian, `message_id`, `file_id`, số lần thử lại và nhật ký lỗi.
- **Tự động thử lại khi mất mạng (Network Retry & Backoff)**:
  - Nếu mất kết nối internet hoặc Telegram bị giới hạn tốc độ (HTTP 429 Rate Limit), hệ thống sẽ đưa file vào hàng đợi và tự động thử lại với độ trễ tăng dần mà không làm treo ứng dụng.
- **Hỗ trợ tệp lên đến 50MB**: Tận dụng tối đa giới hạn upload của Telegram Bot API.

---

## 🤖 Hướng dẫn thiết lập Telegram Bot & Nhóm sao lưu

1. **Tạo Telegram Bot**:
   - Mở Telegram, tìm kiếm bot **`@BotFather`**.
   - Gửi lệnh `/newbot`, đặt tên và username cho bot (ví dụ: `MyBackupFile_bot`).
   - `@BotFather` sẽ gửi cho bạn một **HTTP API Token** (dạng `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).
2. **Tạo Nhóm và lấy Chat ID**:
   - Tạo một nhóm Telegram riêng tư (ví dụ đặt tên: `📁 USB Backups`).
   - Thêm bot vừa tạo vào nhóm và đặt bot làm Quản trị viên (Admin).
   - Thêm bot **`@userinfobot`** hoặc **`@RawDataBot`** vào nhóm để xem **Chat ID** của nhóm (thường là một số âm bắt đầu bằng `-100`, ví dụ `-1002345678901`). Sau khi lấy được Chat ID, bạn có thể xóa bot phụ này ra khỏi nhóm.
3. **Nhập cấu hình vào App**:
   - Mở giao diện ứng dụng, tại mục **☁️ Sao lưu đám mây Telegram Group**, bấm nút **"⚙️ Cấu hình Bot & Nhóm..."**.
   - Dán **Bot Token** và **Chat ID** vào ô tương ứng.
   - Bấm nút **"🔔 Kiểm tra kết nối"**: Bot sẽ gửi một tin nhắn chào mừng vào nhóm để xác nhận thành công!
   - Bấm **"💾 Áp dụng"** (cấu hình Telegram chỉ lưu trong bộ nhớ RAM khi chạy, không lưu vào `config.json` để bảo mật) và tích chọn **"Tự động đồng bộ file lên nhóm Telegram"**.

---

## 📁 Cấu trúc thư mục dự án

```text
usb_save/
│
├── usb_backup.py           # Sao lưu tài liệu Word, PDF, Excel, PowerPoint (Smart Incremental)
├── folder_watcher.py       # Giám sát đệ quy thay đổi thư mục lưu trữ (tệp mới, sửa đổi)
├── telegram_backup.py      # Quản lý upload Telegram, kiểm tra ổn định file (settle), retry
├── telegram_db.py          # SQLite database lưu lịch sử upload và chống trùng lặp
├── config_manager.py       # Quản lý đọc/ghi cấu hình (config.json)
├── config.example.json     # Tệp mẫu cấu hình ban đầu
├── usb_scanner.py          # Quét mã độc, cách ly, tiêm phòng và phục hồi file ẩn
├── usb_detector.py         # Quét và lắng nghe sự kiện cắm/rút USB thời gian thực
├── notifier.py             # Gửi thông báo Windows Toast
├── gui.py                  # Giao diện đồ họa Tkinter & Khay hệ thống (pystray)
├── main.py                 # Điểm khởi chạy chính (hỗ trợ GUI, CLI, Tray)
├── test_app.py             # Bộ kiểm thử bảo mật & sao lưu USB (15 bài test)
├── test_telegram_backup.py # Bộ kiểm thử sao lưu Telegram, SQLite, Watcher (12 bài test)
├── build_exe.bat           # Kịch bản đóng gói thành file thực thi exe độc lập
├── USBSave.spec            # Cấu hình đóng gói PyInstaller
├── requirements.txt        # Danh sách thư viện phụ thuộc
├── run.bat                 # Kịch bản khởi chạy 1-click cho người dùng Windows
├── run_app.vbs             # Kịch bản chạy nền không hiện cửa sổ console
├── .gitignore              # Danh sách loại trừ tệp rác, cache, database khi đẩy lên Git
└── README.md               # Tài liệu hướng dẫn sử dụng
```

---

## 🛠️ Cài đặt & Chuẩn bị môi trường

### Yêu cầu hệ thống
- Hệ điều hành: **Windows 10 / 11** (64-bit khuyên dùng)
- Python: **3.10** trở lên

### Các bước cài đặt
```powershell
# 1. Clone repository về máy tính
git clone https://github.com/hieu-gui-tools/usb_save.git
cd usb_save

# 2. Khởi tạo môi trường ảo Python
python -m venv .venv

# 3. Kích hoạt môi trường ảo
.\.venv\Scripts\activate

# 4. Cài đặt các gói phụ thuộc
pip install -r requirements.txt
```

---

## 🚀 Hướng dẫn khởi chạy

### Cách 1: Khởi chạy nhanh bằng 1 click (Khuyên dùng)
Nhấp đúp chuột vào file `run.bat`. Kịch bản sẽ tự động chuẩn bị môi trường ảo, cài đặt thư viện cần thiết và mở giao diện ứng dụng.

### Cách 2: Khởi chạy bằng dòng lệnh PowerShell
```powershell
# Kích hoạt môi trường ảo
.\.venv\Scripts\activate

# Mở giao diện đồ họa đầy đủ (GUI)
python main.py

# Khởi động và ẩn ngay xuống Khay hệ thống (System Tray)
python main.py --tray

# Chế độ dòng lệnh Console (CLI) có sao lưu và quét bảo mật
python main.py --cli

# Chế độ dòng lệnh CLI kèm tính năng sao lưu Telegram
python main.py --cli --telegram

# Chạy chế độ CLI im lặng hoàn toàn (Tắt thông báo Windows Toast)
python main.py --cli --no-notify

# Chế độ CLI với thư mục sao lưu tùy chỉnh
python main.py --cli --backup-dir "D:\TaiLieu_SaoLuu"
```

---

## 📦 Đóng gói thành file chạy độc lập (.exe)

Nếu muốn tạo file `USBSave.exe` chạy trực tiếp mà không cần cài Python trên máy đích:

```powershell
# Chạy script đóng gói tự động
.\build_exe.bat
```
File thực thi sau khi hoàn tất sẽ nằm trong thư mục `dist\USBSave\`.

---

## 🧪 Kiểm thử tự động

Chạy 2 bộ kiểm thử tự động toàn diện (tổng cộng 27 bài test):
```powershell
# 1. Kiểm thử sao lưu đám mây Telegram, SQLite, debounce và watcher (12 bài test)
python test_telegram_backup.py

# 2. Kiểm thử bảo mật USB, autorun, cách ly, tiêm phòng và sao lưu tài liệu (15 bài test)
python test_app.py
```


