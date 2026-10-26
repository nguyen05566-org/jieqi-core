# jieqi-core

Gomoku auto-cycle bot for Facebook Gaming (`gomoku-vh`).

> ⚠️ **Repo PRIVATE** — repo này chứa file `ck1.txt` (cookie Facebook session).
> KHÔNG đổi sang public. Nếu vô tình đổi, revoke cookie ngay + tạo mới.

## Cấu trúc repo

| File | Mục đích |
|---|---|
| `auto_cycle.py` | Script chính — claim reward → tìm bàn target → SURRENDER → lặp lại |
| `anti_lock.py` | Module chống khóa nick (fingerprint, stealth JS, daily quota) |
| `ck1.txt` | **Cookie Facebook session** (commit vào repo — repo phải private) |
| `.github/workflows/auto_cycle.yml` | GitHub Actions workflow |
| `.gitignore` | Exclude các file nhạy cảm khác (state, fingerprints, ck2.txt...) |

## Cách hoạt động

```
Loop N cycles:
  Phase 1 (CLAIM): Gửi VIDEO_REWARD đến server cho đến khi balance ∈ [claim_min, claim_max]
  Phase 2 (SURRENDER): Mở "Chọn bàn" → tìm bàn của target_name → click "Vào chơi" → gửi SURRENDER
  → Mất bet amount cho target, balance giảm xuống dưới claim_min → claim lại được
```

## Setup

### Bước 1: Set 2 secrets (chỉ làm 1 lần)

Vào https://github.com/nguyen05566-org/jieqi-core/settings/secrets/actions và add:

| Secret name | Value | Ghi chú |
|---|---|---|
| `TARGET_NAME` | `nguyen` | Tên player cần SURRENDER cho |
| `TARGET_ID` | `68952059` | ID nội bộ của target trên gamevh |

(Không cần secret cho cookie — file `ck1.txt` đã có trong repo.)

### Bước 2: Cập nhật cookie khi cần

Khi cookie Facebook expired (sau 7-30 ngày), update file `ck1.txt`:

```bash
# Local
echo "datr=...; c_user=...; xs=...; ..." > ck1.txt
git add ck1.txt
git commit -m "chore: refresh Facebook cookie"
git push
```

### Bước 3: Chạy thử

1. Vào https://github.com/nguyen05566-org/jieqi-core/actions
2. Click workflow **"auto_cycle"**
3. Click **"Run workflow"** (top-right)
4. Chọn `cycles: 1` để test nhỏ
5. Click green **"Run workflow"** button
6. Refresh sau 5s, click vào run mới → xem log live

## Chạy local

```bash
# Cài đặt
pip install playwright
playwright install chromium

# Đảm bảo có file ck1.txt (cookie Facebook)
ls ck1.txt

# Chạy 3 cycles, target "nguyen"
python3 auto_cycle.py \
    --cookie ck1.txt \
    --target-name "nguyen" \
    --target-id 68952059 \
    --cycles 3 \
    --claim-min 50000 \
    --claim-max 55000 \
    --bet-max 100000
```

## Workflow `auto_cycle.yml`

**Triggers:**
- `workflow_dispatch` (chạy thủ công từ tab Actions)
  - Input `cycles`: 1/3/5/10 (mặc định 5)
  - Input `claim_min`: mặc định 50000
  - Input `claim_max`: mặc định 55000
- `schedule`: cron `0 0,6,12,18 * * *` (mỗi 6h — 00:00, 06:00, 12:00, 18:00 UTC = 07:00, 13:00, 19:00, 01:00 giờ VN)

**Steps:**
1. Checkout repo (lấy file `ck1.txt` luôn)
2. Setup Python 3.11
3. Install playwright + chromium
4. Verify `ck1.txt` tồn tại + không rỗng
5. Run `python3 auto_cycle.py` với `SINGLE_COOKIE_FILE=ck1.txt`
6. Upload state artifacts (debug)
7. Auto-restart (disabled by default)

## Lưu ý quan trọng

1. **Phải có người nhận (target) online + tạo bàn trước** khi bot chạy. Nếu target rời bàn, script báo `target not found` và skip cycle đó (không mất xu).
2. **Mỗi SURRENDER = mất bet amount** (thường 40k xu nếu target tạo bàn bet 40k).
3. **Quota claim**: Script không giới hạn, claim đến khi server báo `no response` (game chặn khi balance > 50k).
4. **GH Actions timeout**: Mỗi job chạy tối đa 6h (GitHub-hosted runner).
5. **Cookies expire sau 7-30 ngày** — cần update file `ck1.txt` + push lên repo.

## Đề xuất vận hành

- **2-3 cycles mỗi run** (mỗi cycle ~25-30 phút, tổng ~75-90 phút)
- **Chạy mỗi 6h** để tránh rate-limit server
- **Rotate target**: dùng nhiều account B khác nhau thay vì 1 target duy nhất (chống pattern detection)
- **Monitor logs**: xem tab Actions → click run → "Show log" để theo dõi progress

## Bảo mật

- Repo này **PHẢI private**. Nếu vô tình đổi sang public, **revoke cookie Facebook ngay**:
  1. Vào https://www.facebook.com/settings/security_login → Log out of all sessions
  2. Đổi password Facebook
  3. Lấy cookie mới → update `ck1.txt` → push lên repo
- Token GitHub PAT không lưu trong repo. Nếu token bị leak (e.g. trong chat), revoke ngay tại https://github.com/settings/tokens
