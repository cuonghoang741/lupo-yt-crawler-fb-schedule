# YouTube → Facebook cho Windows · v9

Tool chạy trên máy: tải video YouTube về **Kho video**, render lại (tùy chọn) rồi tự đăng lên Page Facebook theo giờ. Giao diện là một trang web nhỏ chạy trong cửa sổ ứng dụng (pywebview), menu bên trái chia theo nhóm; dải xanh trên cùng luôn ghi **Bước tiếp theo** cho tới khi cài đặt xong.

- **Tổng quan**: bật/tắt tự động, lượt đăng tiếp theo, video sẽ đăng, 5 bước cài đặt.
- **YouTube → Tải thủ công**: dán link video/kênh để tải về. **Kho video**: video đã tải (gộp luôn lịch sử tải), cột **Đăng FB** cho biết video nào đã đăng / chờ đăng / đăng tiếp theo; có nút **Thêm video từ máy**. **Render**: chọn một video trong Kho và render lại sang khung hình khác.
- **Facebook → Tài khoản & Page**: nhiều tài khoản, chọn Chrome/Edge/Firefox, đăng nhập tay và quét Page quản lý. **Lịch đăng & nội dung** lưu riêng theo tài khoản và các Page được tick. **Lịch sử đăng** ghi cả tài khoản, Page, link bài và nhật ký.
- **Cài đặt**: thư mục Kho video, chất lượng, render tự động trước khi đăng, đọc tin, hiện trình duyệt khi gỡ lỗi.

## Ba module chính

Code chia theo đúng pipeline, mỗi bước một module (giao diện ở `webapp.py` + `webui.html`):

1. **`crawl.py`** — tải video về máy, mở rộng link kênh thành danh sách video (dùng `ytcore`).
2. **`render.py`** — render/reframe video đã tải bằng tool **Frame Preview** (vd 9:16 nền mờ), gọi `render_cli.py` của Frame. Dùng ở tab **Render** (chọn video render ngay) hoặc bật **Cài đặt → Render trước khi đăng** để tự render trước mỗi lần đăng. Tắt thì đăng nguyên bản.
3. **`upload.py`** — đăng lên Page Facebook (dùng `fbpost`).

`automation.py` là bộ điều phối nối ba module theo khung giờ. Khi bật render, pipeline chạy: tải → render → đăng.
`accounts.py` quản lý cấu hình từng tài khoản và chuyển dữ liệu từ v8. `webapp.py` là bridge local có token; `webui.html` là giao diện.

### Lịch sử (lưu ra file, mở lại app vẫn còn)

- **Kho video** (gộp lịch sử tải): mỗi video kèm thời gian tải và đường dẫn file; lượt tải lỗi hiện ở bảng dưới.
- **Nhật ký bot**: lưu `logs/bot-YYYY-MM-DD.txt`; nút **Mở nhật ký hôm nay** ở Lịch sử đăng.
- **Lịch sử đăng**: mỗi bài ghi kèm đường dẫn file gốc và file đã render; nút **Mở file đã đăng**.

## Chạy

1. Giải nén zip (chuột phải → Extract All), đừng chạy trong file zip.
2. Bấm đúp `setup.bat`. Lần đầu tool tự cài Python (nếu thiếu), yt-dlp, Playwright và pywebview; lần tải đầu tự tải ffmpeg và deno. Giao diện mở trong cửa sổ ứng dụng (WebView2 có sẵn trên Windows 10/11).
3. Chọn Google Chrome, Microsoft Edge (dùng bản cài trên máy) hoặc Firefox (bản Playwright được `setup.bat` tải riêng).

## Tự đăng Facebook

Làm theo 5 bước ở **Tổng quan** (bấm **Làm ngay →** ở từng bước):

1. **Tài khoản & Page**: dùng tài khoản đầu tiên hoặc bấm **+ Thêm tài khoản**, đặt tên và chọn Chrome/Edge/Firefox. Bấm **Đăng nhập Facebook**, đăng nhập và xác minh trong cửa sổ mở ra, rồi **đóng cửa sổ đó**. Tool kiểm tra phiên sau khi đóng. Mỗi tài khoản có hồ sơ riêng; không cần nhập cookie.
2. **Quét Page ngay**: tool đọc mục Trang quản lý của tài khoản đó. Sang **Lịch đăng & nội dung**, tick các Page muốn đăng. Nếu Facebook đổi giao diện hoặc danh sách không đọc được, tool báo lỗi để bạn mở lại trình duyệt kiểm tra; không lấy Page gợi ý làm Page quản lý.
3. **Nguồn video**: ở **Tải thủ công**, dán link video hoặc link kênh (mỗi dòng một link) để tải về Kho video. Hoặc dùng **Thêm video từ máy** ở Kho video để đưa video có sẵn vào hàng đợi đăng.
4. **Lịch đăng & nội dung**: chọn tài khoản bằng thanh trên, tick Page, nhập giờ (ví dụ `08:00, 12:00, 20h`), nội dung với `{title}`, `{hashtags}`, `{sourceUrl}` và hashtag, rồi **Lưu lịch đăng**. Mỗi khung giờ lấy **video tải về sớm nhất chưa đăng** để đăng lên các Page đã chọn của tài khoản đó. Kho video dùng chung, trạng thái chống trùng tính theo video + Page.
5. **Bật tự động** ở Tổng quan cho tài khoản đang chọn. Tài khoản mới mặc định tắt. Chuyển tài khoản rồi lặp lại các bước để chạy lịch riêng. Nên bấm **Đăng thử 1 video** để kiểm tra trước.

Máy phải bật và mở tool thì mới chạy. Tắt máy quá 30 phút sau một khung giờ thì khung đó bị bỏ qua, không đăng bù. Bot chạy trình duyệt ẩn. Muốn xem bot làm gì (gỡ lỗi), vào **Cài đặt**, tick **Hiện trình duyệt khi bot chạy** rồi **Lưu**; khi đó đừng thao tác trên cửa sổ trình duyệt. Cửa sổ **Đăng nhập Facebook** luôn hiện.

Thao tác Facebook được xếp hàng và chạy lần lượt để tránh hai việc dùng chung một hồ sơ. Khi mở đăng nhập/mở lại trình duyệt, đóng cửa sổ khi xong để tool xử lý việc tiếp theo. Đổi tài khoản trên UI không đổi tài khoản của lệnh đã xếp hàng. Đổi trình duyệt cần tắt tự động và đợi hàng đợi xong, sau đó đăng nhập/kiểm tra lại. Nếu phát hiện hồ sơ đăng nhập nhầm tài khoản, tool dừng trước khi đăng.

### Nâng cấp từ v8

Đóng tool và trình duyệt của tool trước, chép các file chương trình v9 vào thư mục cũ rồi chạy `setup.bat`. Giữ nguyên `automation.json`, `settings.json`, `fb-profile`, `logs` và Kho video. Lần mở đầu tool tạo `automation.v8-backup.json`, đưa cấu hình cũ vào **Tài khoản 1** (hoặc tên Facebook đã lưu) và giữ lịch sử bài đăng. Hồ sơ cũ `fb-profile/<browser>` tiếp tục được dùng. Tài khoản mới lưu ở `fb-profile/accounts/<id>/<browser>`.

Page đã nhập ở v8 được giữ để không mất cấu hình. Khi sửa lịch, quét Page lại rồi chọn từ danh sách quản lý. Gỡ tài khoản chỉ gỡ cấu hình trong app; hồ sơ trên đĩa và lịch sử đăng được giữ.

### Đọc tin (giống bot bản web)

Chọn tài khoản ở thanh trên, vào **Cài đặt → Đọc tin**, nhập từ khóa và bật/tắt cho tài khoản đó rồi **Lưu**. Tool tìm bài theo từ khóa và cuộn đọc 6 lần, mỗi lần cách 10 giây. Lịch đăng được ưu tiên; lượt đọc mỗi giờ chạy khi hàng đợi rảnh. Tool chỉ đọc: không thích, không bình luận, không kết bạn, không đổi dấu vân tay trình duyệt. Gặp đăng nhập/xác minh thì dừng tài khoản đó tới khi bạn đăng nhập lại. Bấm **Đọc tin ngay** để thử.

### Trạng thái bài (mục Lịch sử đăng)

- **Đã đăng**: có link bài.
- **Cần kiểm tra**: đã bấm Đăng nhưng chưa lấy được link. Tool **không tự đăng lại** để tránh trùng. Bấm **Tìm lại bài trên Page**, hoặc mở Page xem: có bài thì **Đánh dấu đã đăng** và dán link; chắc chắn chưa có thì **Cho phép đăng lại**.
- **Lỗi**: lỗi trước khi bấm Đăng, tool thử lại ở khung giờ sau (tối đa 2 lần).

Gặp trang đăng nhập hoặc xác minh, tool dừng và báo; bấm **Đăng nhập Facebook** để xử lý. Tool không vượt qua xác minh của Facebook.

## Đóng gói .exe (tùy chọn)

Chạy `setup.bat` một lần, rồi `Dong-goi-exe.bat`. Kết quả ở `dist\YouTubeFacebook.exe`; bản exe không tự cập nhật yt-dlp.

## Kiểm tra

`python -m unittest discover -s . -p "test_*.py" -v` kiểm tra di chuyển v8, tách hồ sơ/lịch, lệnh giữ đúng tài khoản, chống đăng trùng, quét Page và thao tác UI qua server local thật. Các bài kiểm tra trình duyệt cần Playwright và Chrome; không đăng bài lên Facebook thật. Bản Windows cần kiểm tra đăng nhập/đăng bài thật với tài khoản của bạn vì giao diện Facebook có thể khác theo tài khoản.

Chỉ tải và đăng video bạn có quyền sử dụng.
