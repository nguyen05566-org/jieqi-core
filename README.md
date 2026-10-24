# jieqi-core

Gomoku auto-cycle bot for Facebook Gaming (`gomoku-vh`).

## Cấu trúc repo

| File | Mục đích |
|---|---|
| `auto_cycle.py` | Script chính — claim reward → tìm bàn target → SURRENDER → lặp lại |
| `anti_lock.py` | Module chống khóa nick (fingerprint, stealth JS, daily quota) |
| `.github/workflows/auto_cycle.yml` | GitHub Actions workflow chạy theo schedule |

## Cách hoạt động

```
Loop N cycles:
  Phase 1 (CLAIM): Gửi VIDEO_REWARD đến server cho đến khi balance ∈ [claim_min, claim_max]
  Phase 2 (SURRENDER): Mở "Chọn bàn" → tìm bàn của target_name → click "Vào chơi" → gửi SURRENDER
  → Mất bet amount cho target, balance giảm xuống dưới claim_min → claim lại được
```

## Chạy local

```bash
# Cài đặt
pip install playwright
playwright install chromium

# Tạo file cookie (Facebook session cookies)
echo "datr=...; c_user=...; xs=...; ..." > ck.txt

# Chạy 3 cycles, target "Phat"
python3 auto_cycle.py \
    --cookie ck.txt \
    --target-name "Phat" \
    --target-id 68639698 \
    --cycles 3 \
    --claim-min 50000 \
    --claim-max 55000 \
    --bet-max 100000
```

## Chạy qua GitHub Actions

Workflow `.github/workflows/auto_cycle.yml`:

1. **Trigger thủ công** (workflow_dispatch): chạy bất cứ lúc nào từ tab Actions
2. **Trigger theo schedule** (cron): mỗi 6 giờ tự động chạy

**Setup secrets cần thiết** (Settings → Secrets and variables → Actions):
- `FB_COOKIE` — chuỗi cookie Facebook (giống nội dung file `ck.txt`)
- `TARGET_NAME` — tên player cần SURRENDER cho (vd: `Phat`)
- `TARGET_ID` — ID nội bộ của target (vd: `68639698`)

**Tùy chọn qua env trong workflow:**
- `CYCLES` — số cycle mỗi run (mặc định 5)
- `CLAIM_MIN` / `CLAIM_MAX` — ngưỡng dừng claim (mặc định 50000 / 55000)
- `BET_MAX` — bet tối đa chấp nhận (mặc định 100000)

## Lưu ý quan trọng

1. **Phải có người nhận (target) online + tạo bàn trước** khi bot chạy. Nếu target rời bàn, script báo `target not found` và skip cycle đó (không mất xu).
2. **Mỗi SURRENDER = mất bet amount** (thường 40k xu nếu target tạo bàn bet 40k).
3. **Quota claim**: Script không giới hạn, claim đến khi server báo `no response` (game chặn khi balance > 50k).
4. **GH Actions timeout**: Mỗi job chạy tối đa 6h (GitHub-hosted runner). Workflow auto-restart khi kết thúc.
5. **Cookies cần refresh định kỳ** — Facebook session có thể expire sau 7-30 ngày.

## Đề xuất vận hành

- **2-3 cycles mỗi run** (mỗi cycle ~25-30 phút, tổng ~75-90 phút)
- **Chạy mỗi 6h** để tránh rate-limit server
- **Rotate target**: dùng nhiều account B khác nhau thay vì 1 target duy nhất (chống pattern detection)
- **Monitor logs**: xem tab Actions → click run → "Show log" để theo dõi progress
