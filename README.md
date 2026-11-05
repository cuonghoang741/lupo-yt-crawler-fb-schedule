# YouTube → Facebook cho Windows

Tool chạy trên máy: tải video YouTube về **Kho video**, render lại (tùy chọn) rồi tự đăng lên Page Facebook theo giờ. Giao diện là một trang web nhỏ chạy trong cửa sổ ứng dụng (pywebview), menu bên trái chia theo nhóm; dải xanh trên cùng luôn ghi **Bước tiếp theo** cho tới khi cài đặt xong.

- **Tổng quan**: bật/tắt tự động, lượt đăng tiếp theo, video sẽ đăng, 5 bước cài đặt.
- **YouTube → Tải thủ công**: dán link video/kênh để tải về. **Kho video**: video đã tải (gộp luôn lịch sử tải), cột **Đăng FB** cho biết video nào đã đăng / chờ đăng / đăng tiếp theo; có nút **Thêm video từ máy**. **Render**: chọn một video trong Kho và render lại sang khung hình khác.
- **Facebook → Tài khoản & Page**, **Lịch đăng & nội dung** (có xem trước bài), **Lịch sử đăng** (bài đã đăng, bài cần kiểm tra, nhật ký bot).
- **Cài đặt**: thư mục Kho video, chất lượng, render tự động trước khi đăng, đọc tin, hiện trình duyệt khi gỡ lỗi.

## Ba module chính

Code chia theo đúng pipeline, mỗi bước một module (giao diện ở `webapp.py` + `webui.html`):

1. **`crawl.py`** — tải video về máy, mở rộng link kênh thành danh sách video (dùng `ytcore`).
2. **`render.py`** — render/reframe video đã tải bằng tool **Frame Preview** (vd 9:16 nền mờ), gọi `render_cli.py` của Frame. Dùng ở tab **Render** (chọn video render ngay) hoặc bật **Cài đặt → Render trước khi đăng** để tự render trước mỗi lần đăng. Tắt thì đăng nguyên bản.
3. **`upload.py`** — đăng lên Page Facebook (dùng `fbpost`).

`automation.py` là bộ điều phối nối ba module theo khung giờ. Khi bật render, pipeline chạy: tải → render → đăng.

### Lịch sử (lưu ra file, mở lại app vẫn còn)

- **Kho video** (gộp lịch sử tải): mỗi video kèm thời gian tải và đường dẫn file; lượt tải lỗi hiện ở bảng dưới.
- **Nhật ký bot**: lưu `logs/bot-YYYY-MM-DD.txt`; nút **Mở nhật ký hôm nay** ở Lịch sử đăng.
- **Lịch sử đăng**: mỗi bài ghi kèm đường dẫn file gốc và file đã render; nút **Mở file đã đăng**.

## Chạy

1. Giải nén zip (chuột phải → Extract All), đừng chạy trong file zip.
2. Bấm đúp `setup.bat`. Lần đầu tool tự cài Python (nếu thiếu), yt-dlp, Playwright và pywebview; lần tải đầu tự tải ffmpeg và deno. Giao diện mở trong cửa sổ ứng dụng (WebView2 có sẵn trên Windows 10/11).
3. Cần có Google Chrome hoặc Microsoft Edge (Windows 10/11 luôn có Edge).

## Tự đăng Facebook

Làm theo 5 bước ở **Tổng quan** (bấm **Làm ngay →** ở từng bước):

1. **Đăng nhập Facebook** (mục Tài khoản & Page). Cửa sổ trình duyệt mở ra: đăng nhập bằng tài khoản quản lý Page, xác minh nếu Facebook hỏi, rồi **đóng cửa sổ đó**. Tool lưu phiên trong thư mục `fb-profile`; không cần cookie. Đăng nhập xong tool tự chuyển tới phần thêm Page.
2. **Thêm Page**: nhập Tên Page (đúng như tên hiển thị trên Facebook) và link Page, ví dụ `https://www.facebook.com/profile.php?id=100091470829341`, bấm **+ Thêm Page**.
3. **Nguồn video**: ở **Tải thủ công**, dán link video hoặc link kênh (mỗi dòng một link) để tải về Kho video. Hoặc dùng **Thêm video từ máy** ở Kho video để đưa video có sẵn vào hàng đợi đăng.
4. **Lịch đăng & nội dung**: giờ đăng (ví dụ `08:00, 12:00, 20h`), nội dung với `{title}`, `{hashtags}`, `{sourceUrl}`, hashtag, rồi **Lưu lịch đăng**. Mỗi khung giờ tool lấy **video tải về sớm nhất chưa đăng** trong Kho và đăng lên mọi Page. Muốn bỏ một video khỏi hàng đợi thì xóa nó trong Kho video.
5. **Bật tự động** ở Tổng quan. Nên bấm **Đăng thử 1 video ngay** một lần để thử.

Máy phải bật và mở tool thì mới chạy. Tắt máy quá 30 phút sau một khung giờ thì khung đó bị bỏ qua, không đăng bù. Bot chạy trình duyệt ẩn. Muốn xem bot làm gì (gỡ lỗi), vào **Cài đặt**, tick **Hiện trình duyệt khi bot chạy** rồi **Lưu**; khi đó đừng thao tác trên cửa sổ trình duyệt. Cửa sổ **Đăng nhập Facebook** luôn hiện.

### Đọc tin (giống bot bản web)

Trong **Cài đặt → Facebook nâng cao**: điền từ khóa (cách nhau bằng dấu phẩy), tick **Đọc tin mỗi giờ**, bấm **Lưu**. Mỗi giờ tool chọn ngẫu nhiên một từ khóa, mở trang tìm bài viết trên Facebook và cuộn đọc 6 lần, mỗi lần cách 10 giây. Tool chỉ đọc: không thích, không bình luận, không kết bạn, không đổi dấu vân tay trình duyệt. Gặp đăng nhập/xác minh thì dừng đọc tin cho tới khi bạn đăng nhập lại. Bấm **Đọc tin ngay** để thử một lượt.

### Trạng thái bài (mục Lịch sử đăng)

- **Đã đăng**: có link bài.
- **Cần kiểm tra**: đã bấm Đăng nhưng chưa lấy được link. Tool **không tự đăng lại** để tránh trùng. Bấm **Tìm lại bài trên Page**, hoặc mở Page xem: có bài thì **Đánh dấu đã đăng** và dán link; chắc chắn chưa có thì **Cho phép đăng lại**.
- **Lỗi**: lỗi trước khi bấm Đăng, tool thử lại ở khung giờ sau (tối đa 2 lần).

Gặp trang đăng nhập hoặc xác minh, tool dừng và báo; bấm **Đăng nhập Facebook** để xử lý. Tool không vượt qua xác minh của Facebook.

## Đóng gói .exe (tùy chọn)

Chạy `setup.bat` một lần, rồi `Dong-goi-exe.bat`. Kết quả ở `dist\YouTubeFacebook.exe`; bản exe không tự cập nhật yt-dlp.

Chỉ tải và đăng video bạn có quyền sử dụng.
