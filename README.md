# YouTube Downloader cho Windows

Tool chạy trên máy, có ba tab:

1. **Tải video**: dán link video hoặc kênh YouTube (mỗi dòng một link), hoặc import CSV/TXT. Link kênh tải tất cả video công khai, cả Shorts.
2. **Thư viện**: xem video đã tải theo kênh, tìm, mở, lưu thumbnail, xóa.
3. **Facebook & Tự động**: đăng nhập Facebook một lần, tự cào kênh mới và tự đăng lên Page theo khung giờ.

## Chạy

1. Giải nén zip (chuột phải → Extract All), đừng chạy trong file zip.
2. Bấm đúp `setup.bat`. Lần đầu tool tự cài Python (nếu thiếu), yt-dlp và Playwright; lần tải đầu tự tải ffmpeg và deno.
3. Cần có Google Chrome hoặc Microsoft Edge (Windows 10/11 luôn có Edge).

## Tự đăng Facebook

1. Tab **Facebook & Tự động** → **Đăng nhập Facebook**. Cửa sổ trình duyệt mở ra: đăng nhập bằng tài khoản quản lý Page, xác minh nếu Facebook hỏi, rồi **đóng cửa sổ đó**. Tool lưu phiên trong thư mục `fb-profile`; không cần cookie.
2. **Page đăng**: mỗi dòng `Tên Page | link Page`, ví dụ `Hà Huệ | https://www.facebook.com/profile.php?id=100091470829341`. Tên phải đúng như trong bộ chọn Page của Facebook. Dòng bắt đầu bằng `#` bị bỏ qua.
3. **Kênh tự cào**: mỗi dòng một link kênh. Lần quét đầu chỉ ghi mốc, không tải lại lịch sử kênh; từ đó cứ 15 phút tool tải video mới về Thư viện.
4. **Khung giờ**: ví dụ `08:00, 12:00, 20h`. Mỗi khung giờ tool lấy **video tải về sớm nhất chưa đăng** trong Thư viện và đăng lên mọi Page đã liệt kê. Muốn bỏ một video khỏi hàng đợi thì xóa nó trong Thư viện.
5. Viết **Nội dung bài** với `{title}`, `{hashtags}`, `{sourceUrl}`, tick **Bật tự cào và tự đăng**, bấm **Lưu cài đặt**. Nên bấm **Đăng 1 video ngay** một lần để thử.

Máy phải bật và mở tool thì mới chạy. Tắt máy quá 30 phút sau một khung giờ thì khung đó bị bỏ qua, không đăng bù. Bot chạy trình duyệt ẩn. Muốn xem bot làm gì (gỡ lỗi), tick **Hiện trình duyệt khi bot chạy** rồi **Lưu cài đặt**; khi đó đừng thao tác trên cửa sổ trình duyệt. Cửa sổ **Đăng nhập Facebook** luôn hiện.

### Đọc tin (giống bot bản web)

Điền **Từ khóa đọc tin** (cách nhau bằng dấu phẩy), tick **Đọc tin mỗi giờ**, bấm **Lưu cài đặt**. Mỗi giờ tool chọn ngẫu nhiên một từ khóa, mở trang tìm bài viết trên Facebook và cuộn đọc 6 lần, mỗi lần cách 10 giây. Tool chỉ đọc: không thích, không bình luận, không kết bạn, không đổi dấu vân tay trình duyệt. Gặp đăng nhập/xác minh thì dừng đọc tin cho tới khi bạn đăng nhập lại. Bấm **Đọc tin ngay** để thử một lượt.

### Trạng thái bài

- **Đã đăng**: có link bài.
- **Cần kiểm tra**: đã bấm Đăng nhưng chưa lấy được link. Tool **không tự đăng lại** để tránh trùng. Bấm **Tìm lại bài trên Page**, hoặc mở Page xem: có bài thì **Đánh dấu đã đăng** và dán link; chắc chắn chưa có thì **Cho phép đăng lại**.
- **Lỗi**: lỗi trước khi bấm Đăng, tool thử lại ở khung giờ sau (tối đa 2 lần).

Gặp trang đăng nhập hoặc xác minh, tool dừng và báo; bấm **Đăng nhập Facebook** để xử lý. Tool không vượt qua xác minh của Facebook.

## Đóng gói .exe (tùy chọn)

Chạy `setup.bat` một lần, rồi `Dong-goi-exe.bat`. Kết quả ở `dist\YouTubeDownloader.exe`; bản exe không tự cập nhật yt-dlp.

Chỉ tải và đăng video bạn có quyền sử dụng.
