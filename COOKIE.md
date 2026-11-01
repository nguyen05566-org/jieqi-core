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

## 7. Exit code & vòng restart của workflow

| Code | Ý nghĩa | Workflow làm gì |
|---|---|---|
| 0 | Chạy xong (có cycle) | kết thúc job, xanh |
| 1 | Lỗi tạm thời: không có cycle, game frame không lên, browser crash lẻ | retry (10–30s), tới `MAX_RUNTIME` |
| 2 | Browser crash | retry 30s |
| **3** | **Session đã bị server thu hồi / checkpoint / cookie file thuộc account khác** | **dừng hẳn job, `::error::` đỏ — KHÔNG retry** |

Trước đây login wall cũng trả 1 ⇒ job retry 10s/lần suốt 5h: hàng trăm lần mở
login wall, account càng khó sống và log đầy lỗi. Nay `EXIT_SESSION_DEAD = 3`
được trả ở 3 chỗ: kiểm tra login lúc setup, `find_game_frame` thất bại + xác
nhận session chết, và khi `c_user` của phiên khác `c_user` trong file (nhầm
account — trường hợp này còn nguy hiểm hơn crash vì xu có thể đi sai account).

## 8. Dọn dẹp workflow

- Đã xoá **22 workflow trỏ tới `ck*.txt` không tồn tại** (`ck16–19`, `ck22–29`,
  `ck37–45`, `ck60`): chúng fail ngay ở bước "Verify cookie file" mỗi 6h, chỉ
  tạo run đỏ. Script `auto_cycle_ckNN.py` tương ứng vẫn còn — chỉ cần thêm
  `ckNN.txt` rồi copy `ck12.yml` là chạy lại được.
- Đã xoá **`ck35.yml`, `ck36.yml`**: trùng account với `ck3.txt` / `ck6.txt`
  (cùng `c_user`) ⇒ hai browser dùng chung một `xs`, Facebook thu hồi ngay.
  `ck35.txt` / `ck36.txt` vẫn còn trong repo: nếu bản trong đó còn sống, dán
  sang `ck3.txt` / `ck6.txt` rồi xoá file trùng.
- `.gitignore`: bỏ ignore `ck2..ck11` — chúng vẫn được workflow dùng, ignore chỉ
  làm account mới dễ bị bỏ sót khỏi git.
- Test `tests/test_cookie_utils.py` giờ chặn tái phát: mỗi workflow phải trỏ
  tới cookie file tồn tại, và không hai workflow nào dùng chung một account.

## 9. Giới hạn của cache

`actions/cache` lưu ở post-step và **chỉ lưu khi job thành công**. Vì vậy:
- Job fail/cancel ⇒ jar của run đó không vào cache ⇒ token vừa rotate bị mất,
  run sau quay lại bản cũ. Đây là lý do vẫn nên giữ `MAX_RUNTIME` **ngắn hơn**
  khoảng cron (5h < 6h) và tránh trigger tay khi job đang chạy
  (`cancel-in-progress: true`).
- Xảy ra thường xuyên thì chuyển sang commit `ck*.txt` + `state/cookies/` lại
  vào repo sau mỗi run (cần `contents: write`), nhưng sẽ làm git history chứa
  session token và có thể đụng nhau khi nhiều workflow push cùng lúc.

## 10. Test

```bash
python3 tests/test_cookie_utils.py    # 29 test, không cần playwright
```
