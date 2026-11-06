# Facebook Poster

Bản sửa kết nối: **2026.11.06.1** (hiện dưới tên app trong menu).

Tool đăng video lên Page Facebook, nhiều tài khoản, đăng tay. Chạy trên Windows. Không tải YouTube, không tự động.

- **Tài khoản & Page**: thêm nhiều tài khoản (mỗi tài khoản một trình duyệt + hồ sơ riêng). Đăng nhập Facebook, **Quét Page** tài khoản sở hữu hoặc **nhập link Page tay**.
- **Đăng bài**: chọn video từ máy (gồm video tải/render từ tool YouTube Downloader) → chọn Page của tài khoản → viết nội dung → **Đăng ngay**.
- **Lịch sử đăng**: bài đã đăng / cần kiểm tra, tìm lại bài, nhật ký.

Có thể dùng Google Chrome/Edge đã cài, hoặc Chromium/Firefox được setup.bat tải riêng cho tool. Mỗi tài khoản và mỗi trình duyệt có hồ sơ riêng.

## Chạy
1. Giải nén, bấm đúp `setup.bat` (lần đầu tự cài Python, Playwright, pywebview, Chromium và Firefox).
2. Thêm tài khoản → Đăng nhập Facebook → Quét Page → sang Đăng bài.

## Khi không mở được cửa sổ đăng nhập

1. Đóng tool cũ, giải nén đè các file chương trình mới vào thư mục cũ rồi chạy lại **setup.bat**. Giữ `accounts.json`, `fb-profile` và `logs`.
2. Trong Tài khoản & Page, chọn đúng tài khoản. Nếu Chrome/Edge không mở được, chọn **Chromium (đi kèm tool)** rồi bấm **Đăng nhập Facebook**. Khi đổi trình duyệt cần đăng nhập lại trong hồ sơ riêng; hồ sơ cũ được giữ nguyên.
3. Đăng nhập/xác minh Facebook bằng tay, rồi đóng cửa sổ đăng nhập để tool kiểm tra và lưu trạng thái.

Trạng thái và lỗi hiện ngay dưới nút đăng nhập, kèm mã lỗi để hỗ trợ:

- `BROWSER_NOT_FOUND`: Chrome/Edge đã chọn không tìm thấy. Chọn Chromium hoặc cài trình duyệt đó.
- `BROWSER_NOT_INSTALLED`: thiếu bản Chromium/Firefox phù hợp với Playwright; chạy lại setup.bat.
- `PROFILE_IN_USE`: một cửa sổ/tool khác đang dùng hồ sơ; đóng cửa sổ đó rồi thử lại. Không xóa hồ sơ.
- `PROFILE_NOT_WRITABLE`: giải nén vào thư mục có quyền ghi (ví dụ thư mục riêng trong Documents), không chạy trực tiếp trong ZIP.
- `SESSION_CHECK_FAILED`: cửa sổ đã mở nhưng chưa kiểm tra được Facebook; kiểm tra mạng rồi bấm Kiểm tra lại.

Nếu tải Facebook chậm, cửa sổ được giữ để người dùng thao tác tay. Không bấm Đăng nhập liên tục: lệnh trùng được bỏ qua. Nhật ký kết nối nằm tại màn Tài khoản & Page và file `logs/facebook-poster-YYYY-MM-DD.log`.

Nếu app không mở hoặc cần xem lỗi khởi động, chạy **chay-co-log.bat**; xem `logs/startup.log`. Tool không tự gửi nhật ký hay hồ sơ ra ngoài.

## Kiểm tra bản sửa

Chạy `python -m unittest discover -s . -p "test_*.py" -v` trong môi trường đã cài phụ thuộc. 14 kiểm thử đã đạt trên Mac: tìm đường dẫn Windows (mô phỏng), lỗi hồ sơ/trình duyệt, lệnh trùng, UI và mở cửa sổ Chrome/Chromium thật với Facebook giả lập. Chưa xác nhận trên máy Windows của khách hoặc đăng nhập Facebook thật trong lần sửa này.
