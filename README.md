# CloakBrowser Login Pro

Ứng dụng desktop Windows để quản lý browser profile CloakBrowser/Chromium theo phong cách GoLogin: giao diện sáng, bảng profile, proxy, extension, bookmark, kiểm tra proxy/fingerprint và mở mỗi profile bằng một cửa sổ browser riêng.

## Tải bản chạy sẵn

Phiên bản đầu tiên: **0.1.0**

Bạn có thể chọn một trong hai bản:

### Bản cài đặt trực tiếp

[Download Installer EXE 0.1.0](https://github.com/Anhquocqh25/Cloakbrowser-Login-Pro/raw/main/release/CloakBrowser-Login-Pro-Setup-0.1.0-Windows.exe)

1. Tải file EXE ở link trên.
2. Mở file `CloakBrowser-Login-Pro-Setup-0.1.0-Windows.exe`.
3. Bấm Next/Install để cài app.
4. Sau khi cài, mở app từ Start Menu hoặc shortcut Desktop nếu đã chọn.

Installer cài theo user hiện tại, không cần quyền Administrator.

### Bản portable

[Download Portable ZIP 0.1.0](https://github.com/Anhquocqh25/Cloakbrowser-Login-Pro/raw/main/release/CloakBrowser-Login-0.1.0-Windows.zip)

1. Tải file ZIP.
2. Giải nén ra một thư mục bất kỳ.
3. Mở `CloakBrowser Login.exe`.

Bản portable phù hợp nếu bạn muốn chạy trực tiếp, không cần cài vào Windows.

## Chức năng chính

- Quản lý profile browser độc lập.
- Tạo một profile hoặc tạo hàng loạt profile.
- Mở/xóa hàng loạt profile.
- Quản lý proxy, kiểm tra proxy live/dead, tự lấy IP, vị trí, quốc gia, múi giờ.
- Hiển thị proxy đang dùng ngay trên bảng profile.
- Dropdown chọn timezone có UTC offset, ví dụ `UTC +07:00 · Asia/Bangkok`.
- Dropdown chọn language/locale.
- Tự đồng bộ timezone/locale theo proxy đã check.
- Quản lý extension mặc định.
- Quản lý bookmark mặc định.
- Startup website mặc định toàn app và tùy chỉnh riêng từng profile.
- Kiểm tra hồ sơ trước khi chạy: proxy, IP, timezone, WebRTC, DNS và consistency fingerprint.
- Fingerprint Lab: CloakBrowser version, Consistency Engine, snapshot/diff, Seed Lock, Duplicate Detector, Regression Test.
- Thùng rác profile, khôi phục hoặc xóa vĩnh viễn sau thời gian giữ.
- Hỗ trợ giao diện tiếng Việt/tiếng Anh.
- DuckDuckGo là công cụ tìm kiếm mặc định của các profile mới và hiện có.
- Kiểm tra, tải và xác minh cập nhật ngay trong trang Cài đặt.
- Bản installer tự chạy bộ cài mới; bản portable tự thay thế tệp ứng dụng sau khi đóng app.

## Chạy từ source code

Yêu cầu:

- Windows
- Python 3.11+

Mở PowerShell trong thư mục dự án và chạy:

```powershell
.\setup.ps1
.\run.ps1
```

Hoặc mở nhanh bằng:

```powershell
Start CloakBrowser Login.cmd
```

## Build EXE

```powershell
.\build_exe.ps1
```

Sau khi build, file chạy nằm trong:

```text
dist\CloakBrowser Login\CloakBrowser Login.exe
```

## Dữ liệu cục bộ

App lưu dữ liệu profile, cấu hình, proxy, extension và bookmark tại:

```text
%LOCALAPPDATA%\CloakBrowser Login
```

Không nên commit dữ liệu trong thư mục này lên GitHub.

## Phát hành bản cập nhật

Mỗi bản mới cần build lại cả installer và portable, tính SHA-256 của hai tệp rồi cập nhật `release/latest.json`. App đọc tệp này từ GitHub, so sánh version và chỉ cài gói có mã SHA-256 khớp. Dữ liệu profile vẫn nằm trong `%LOCALAPPDATA%\CloakBrowser Login` nên không bị ghi đè khi nâng cấp.

## Phiên bản

- `0.1.0`: bản public đầu tiên.

Các bản cập nhật sau này sẽ nâng version lên tiếp theo.
