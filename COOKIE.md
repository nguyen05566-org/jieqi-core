# Cookie: cơ chế lưu / khôi phục + cách đọc trạng thái login

Tài liệu ngắn cho phần cookie sau khi bỏ cơ chế "kéo dài `expires` 400 ngày"
(không có tác dụng: `expires` chỉ là metadata của trình duyệt, Facebook quyết
định hạn session ở server).

## 1. Cookie được lưu ở đâu

| File | Vai trò | Ghi bởi |
|---|---|---|
| `ck<n>.txt` | nguồn chính, định dạng phẳng `a=b; c=d`, sửa tay được | người dùng **và** bot (tự ghi lại khi thoát) |
| `state/cookies/ck<n>.txt.jar.json` | bản đầy đủ: `domain/path/secure/httpOnly/sameSite/expires` + `history` | bot (autosave) |

`state/` đã nằm trong `.gitignore`; trên GitHub Actions thư mục này được giữ
giữa các run bằng bước cache `Cookie jar cache` trong từng workflow.

## 2. Vì sao không còn bịa `expires`

- Cookie Facebook cấp (`c_user`, `xs`, `datr`, `sb`, …) là **session cookie**
  (không có `expires`). Code cũ gán `now + 400 ngày` cho tất cả → không ảnh
  hưởng gì tới server, chỉ làm mất tín hiệu "cookie này sắp hết hạn".
- Từ giờ: cookie giữ nguyên `expires` nếu server cấp, không có thì vẫn là
  session cookie (`prepare_cookie` bỏ hẳn field khi không có giá trị thật).

## 3. Run này đọc cookie nào (quy tắc "lineage")

`load_cookies(path)` so khớp **digest nội dung `ck*.txt`** với `history` trong jar:

- digest **có** trong history ⇒ txt này do chính bot ghi ra ở run trước ⇒ **jar
  mới hơn** (chứa giá trị server cấp gần nhất, kể cả khi txt trong git là bản
  cũ) ⇒ dùng jar.
- digest **không** có ⇒ người dùng vừa dán cookie mới vào txt ⇒ **txt thắng**,
  jar chỉ bù những cookie mà txt không có.

Không dùng `mtime` vì trên CI mtime luôn là thời điểm checkout.

## 4. Khi nào bot ghi lại cookie

- ngay sau khi xác nhận đã login (lấy `datr`/`sb`/`xs` mà FB vừa cấp),
- đầu mỗi cycle (throttle `COOKIE_SAVE_INTERVAL`, mặc định 300s),
- trước khi `restart_browser()` vứt context,
- khi process thoát: `atexit` + `SIGTERM`/`SIGINT` (GitHub cancel job).

`save_cookies()` **từ chối ghi** nếu context không còn đủ `c_user` + `xs`, nên
file tốt không bị ghi đè bằng session rỗng. Cookie có trong file mà run này
không chạm tới (`sb`, `fr`, …) vẫn được giữ nguyên.

## 5. Đọc trạng thái login: `detect_login_state()`

Kết luận chỉ dựa trên bằng chứng:

1. cookie `c_user` + `xs` có trong context hay không,
2. URL (login / checkpoint / hai-step),
3. DOM: form mật khẩu **đang hiển thị** + dấu hiệu nav/profile của FB,
4. HTTP status của document (401/403), và `c_user` có khớp file cookie không
   (`user_switched`).

Kết quả: `logged_in` / `logged_out` / `checkpoint` / `unknown`. Chữ "Đăng nhập"
nằm đâu đó trong `innerText` **không** còn là căn cứ để kill run — trước đây nó
làm bot báo "cookie hết hạn" cả khi session còn sống (consent dialog, DOM chưa
render).

## 6. Việc cần làm thủ công (không thể tự động)

Client không thể gia hạn session phía server. Khi thật sự bị thu hồi (đổi mật
khẩu, checkpoint, IP/thiết bị lạ, sống quá lâu không hoạt động), phải đăng nhập
lại trên trình duyệt và dán chuỗi cookie mới vào `ck<n>.txt` — bot sẽ nhận ra
(vì digest không khớp history) và dùng đúng bản bạn vừa dán.

## 7. Test

```bash
python3 tests/test_cookie_utils.py    # không cần playwright
```
