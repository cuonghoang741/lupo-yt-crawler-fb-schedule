# Kiểm tra v10 · 2026-11-05

39 bài kiểm thử tự động trên macOS, Python 3.14, Chrome/Playwright và yt-dlp. Không dùng tài khoản thật hoặc tải video từ YouTube/Facebook trong các bài kiểm tra.

- Các kiểm tra v9 tiếp tục chạy: di chuyển dữ liệu, tách tài khoản/hồ sơ, Page quản lý, lịch riêng, đánh dấu trước khi gửi và chống đăng trùng.
- Nhập Netscape cookies.txt, loại cookie ngoài YouTube, từ chối cookie hết hạn/sai định dạng mà không làm mất phiên cũ hoặc đưa giá trị cookie lên UI.
- Dùng thư viện yt-dlp thật để đọc cookie từ bản sao trong RAM; không ghi ngược vào file phiên gốc.
- Quét kênh và tải video đều dùng cùng cấu hình phiên, chất lượng và công cụ tải.
- Lỗi yêu cầu đăng nhập dừng ngay video đầu; các mục khác vẫn Chờ. Đóng/mở lại app vẫn giữ hàng đợi và trạng thái tạm dừng.
- Tiếp tục/thử lại tất cả hoặc từng mục, giới hạn 429, phục hồi mục đang tải khi app bị tắt.
- Quét kênh bị ngắt rồi thử lại không nhân đôi các video đã liệt kê.
- Import CSV, file mẫu và tiêu đề gốc; nhập MP4/MKV từ máy hiện đúng trong Kho.
- Thumbnail chỉ được đọc qua URL ngẫu nhiên đã đăng ký từ Kho, không nhận đường dẫn file tùy ý.
- UI chạy qua bridge loopback thật: import link, nhập cookie, chọn phiên, nhóm/thu gọn kênh, thử lại lỗi và lưu file mẫu; không lỗi JavaScript.
- Kiểm tra cú pháp Python/JavaScript, diff và cấu trúc ZIP; gói phát hành không chứa video, cookie, hồ sơ đăng nhập hay hàng đợi cá nhân.

Giới hạn: chưa chạy trực tiếp trên Windows và chưa xác minh đăng nhập Google/YouTube hoặc tải bằng phiên thật của người dùng. Google có thể từ chối trình duyệt tự động; có đường nhập cookies.txt từ trình duyệt đã đăng nhập. Cookie không đảm bảo mọi video hoặc lượt tải được chấp nhận. Tool dừng để người dùng xác minh; không tự giải CAPTCHA, đổi danh tính hoặc vượt kiểm tra truy cập.

ZIP chứa mã nguồn và setup.bat, không phải EXE đã build trên Windows. Giữ dữ liệu và thư mục hồ sơ khi nâng cấp, chạy lại setup.bat để cập nhật phụ thuộc, sau đó vào Tải thủ công → Phiên YouTube và Tiếp tục / thử lại lỗi.
