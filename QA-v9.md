# Kiểm tra v9 · 2026-11-05

28/28 bài kiểm thử đạt trên macOS, Python 3.14, Chrome và Playwright; thời gian 176,6 giây.

- Di chuyển dữ liệu v8 một lần, tạo bản sao lưu, giữ lịch và lịch sử bài đăng.
- Mỗi tài khoản/trình duyệt có thư mục riêng, dùng lại hồ sơ v8.
- Lịch đăng, nội dung, Page, từ khóa và bật/tắt đọc tin lưu riêng theo tài khoản.
- Lệnh đăng nhập/quét Page đã xếp hàng không đổi tài khoản khi UI đổi lựa chọn.
- Chặn Page từ tài khoản khác; kiểm tra đúng người dùng trước khi dùng phiên Facebook.
- Hai lịch chạy đúng hồ sơ và nội dung, không chạy lại cùng khung giờ.
- Không tự đăng lại bài đã đăng hoặc đang cần kiểm tra, kể cả Page đổi từ vanity URL sang ID đã xác minh.
- UI web chạy qua bridge loopback thật: thêm tài khoản Firefox, chọn Page, lưu lịch riêng, đổi tài khoản; không lỗi JavaScript.
- Bộ quét trên trang giả lập lấy Page quản lý, bỏ Trang gợi ý và link giả mạo tên miền.
- Luồng composer/reel, đánh dấu trước khi gửi, đọc tin và thao tác YouTube cũ vẫn đạt.
- Kiểm tra cú pháp Python/JavaScript và diff không có lỗi khoảng trắng.

Kiểm thử không truy cập hoặc đăng bài lên Facebook thật. Chưa chạy trực tiếp trên Windows, chưa kiểm tra việc đăng nhập Facebook hoặc giao diện Page riêng của từng tài khoản. Các thao tác đó cần xác minh trên máy Windows có tài khoản của người dùng. Gặp đăng nhập/xác minh hoặc không đọc được Page thì tool dừng/báo lỗi để người dùng xử lý.

Gói phát hành chỉ chứa mã chương trình, hướng dẫn, script cài đặt và kiểm thử; không chứa cookie, hồ sơ trình duyệt, cấu hình tài khoản, video hoặc nhật ký cá nhân. Chạy `setup.bat` trên Windows; gói ZIP này là mã nguồn kèm bộ cài phụ thuộc, không phải EXE đã build trên Windows.
