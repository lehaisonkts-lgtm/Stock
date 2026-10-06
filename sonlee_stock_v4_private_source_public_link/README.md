# SONLEE STOCK — V4 Public Link / Private Source

Ứng dụng Python/Streamlit để sàng lọc và nghiên cứu cổ phiếu Việt Nam theo 6 tiêu chí đầu tư, đồng thời theo dõi **biểu đồ nến Nhật ngày + khối lượng** cho từng mã.

> Bản V4 được chuẩn hóa để deploy bằng **GitHub Private + Streamlit Community Cloud**. Người xem dùng link public nhưng không có quyền truy cập source. Các trang chỉnh dữ liệu gốc chỉ mở khi Admin đăng nhập bằng mật khẩu đặt trong Streamlit Secrets.

**URL đề xuất:** `https://stock-sonlee.streamlit.app`

**Entrypoint deploy:** `streamlit_app.py`

Xem hướng dẫn chi tiết tại `DEPLOY_STREAMLIT.md`.

## 6 tiêu chí đầu tư

1. Ngành có "thiên thời", còn dư địa tăng trưởng, tránh ngành suy thoái/bão hòa.
2. Nhà nước trực tiếp nắm >50% hoặc doanh nghiệp Nhà nước chi phối >50%.
3. Lãnh đạo có hiệu quả sử dụng vốn, sở hữu cổ phiếu, tập trung ngành chính và quan tâm quyền lợi cổ đông.
4. Có bằng chứng về tài sản ẩn/chưa phản ánh đầy đủ trong thuyết minh BCTC.
5. Tăng trưởng quý >10%, biên lợi nhuận năm >30% và > benchmark ngành.
6. Ưu tiên cổ tức đều đặn.

## Điểm mới V4 — Public link / Private source

- Brand giao diện: **SONLEE STOCK**.
- Public Viewer chỉ thấy các trang xem/phân tích.
- Admin unlock bằng `ADMIN_PASSWORD` trong Streamlit Secrets.
- `.gitignore` chặn secrets, SQLite, backup và file runtime.
- `streamlit_app.py` là entrypoint ổn định cho Community Cloud.
- Giữ toàn bộ chức năng dữ liệu giá ngày của V3.

## Dữ liệu giá ngày

### Biểu đồ nến Nhật + volume

Trang **Biểu đồ giá & khối lượng** có:

- OHLCV khung ngày `1D`.
- Nến tăng/giảm và cột khối lượng phía dưới.
- MA20, MA50 và đường khối lượng trung bình 20 phiên.
- Chọn khung: 1M, 3M, 6M, 1Y, 3Y, 5Y, MAX.
- KPI phiên mới nhất: đóng cửa, % thay đổi, mở cửa, cao/thấp, volume, volume/TB20, 52W high-low.
- ATR14, MA20, MA50, volume TB20.
- Xuất dữ liệu OHLCV ra CSV.
- Nút **CẬP NHẬT DỮ LIỆU** để bỏ cache 15 phút và gọi nguồn live ngay.
- Nếu nguồn live lỗi, app tự fallback sang dữ liệu SQLite đã tải trước đó.

### 13 mã bắt buộc

App ghim sẵn các mã:

`CKA, KSV, CSV, VEA, TMB, CST, HU4, HUD, HD8, L14, CLM, FT1, FOX`

Các mã này **không phụ thuộc kết quả sàng lọc**. Trang chart có nút **CẬP NHẬT 13 MÃ BẮT BUỘC** để tải 3 năm OHLCV cho toàn bộ nhóm.

Danh sách này có thể chỉnh tại:

**Dữ liệu & cấu hình → Mã bắt buộc**

## Cập nhật dữ liệu hàng ngày

Có 3 cơ chế:

1. **Khi mở chart**: app tự gọi dữ liệu live; kết quả cache 15 phút để không spam API.
2. **Cập nhật thủ công**: nút CẬP NHẬT DỮ LIỆU hoặc CẬP NHẬT 13 MÃ BẮT BUỘC.
3. **Batch cuối ngày**: chạy `run_daily_update.bat`. Script cập nhật 3 năm OHLCV cho 13 mã bắt buộc và toàn bộ mã trong Watchlist, sau đó lưu vào SQLite.

Có thể dùng Windows Task Scheduler để chạy `run_daily_update.bat` mỗi ngày làm việc sau khi thị trường đóng cửa.

## Giao diện chính

1. **Tổng quan** — dashboard, Top cơ hội, pipeline nghiên cứu.
2. **Sàng lọc & xếp hạng** — mô hình 6 tiêu chí, hard-gate, benchmark ngành.
3. **Quét sở hữu Nhà nước** — tạo universe doanh nghiệp Nhà nước chi phối >50%.
4. **Biểu đồ giá & khối lượng** — OHLCV ngày, nến Nhật, volume, MA, cache live.
5. **Phân tích doanh nghiệp** — checklist, điểm thành phần, quản trị, cổ tức, Adjusted NAV.
6. **Soi BCTC & tài sản ẩn** — quét PDF và lưu bằng chứng theo file/trang.
7. **Watchlist & luận điểm** — quản lý pipeline nghiên cứu và giả định giá.
8. **Dữ liệu & cấu hình** — override, thiên thời, registry Nhà nước, benchmark, mã bắt buộc, backup.
9. **Lịch sử & mô hình** — audit trail và mô hình 100 điểm.

## Nguồn dữ liệu giá

Code ưu tiên Unified Market API của `vnstock 4.x`:

```python
from vnstock import Market

mkt = Market()
df = mkt.equity("VEA").ohlcv(
    start="2025-01-01",
    end="2026-10-06",
    interval="1D",
)
```

Nếu Market layer không trả dữ liệu, provider thử fallback qua VCI bằng Unified `Vnstock()` API.

Schema được chuẩn hóa về:

`date, open, high, low, close, volume`

## Cache SQLite

Bảng `market_ohlcv` lưu:

- ticker;
- date;
- open/high/low/close;
- volume;
- source;
- thời điểm refresh.

Khóa chính là `(ticker, date)`, nên việc cập nhật hàng ngày là idempotent và không sinh bản ghi trùng.

## Cài đặt trên Windows

1. Giải nén thư mục.
2. Nhấp đúp `run_pc.bat`.
3. Lần đầu script tạo `.venv`, cài thư viện và mở app tại `http://localhost:8501`.

Script đã dùng thêm Vnstock package index:

```bash
python -m pip install --extra-index-url https://vnstocks.com/api/simple -r requirements.txt
```

Cách thủ công:

```bash
py -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install --extra-index-url https://vnstocks.com/api/simple -r requirements.txt
python -m streamlit run app.py
```

## Dùng trên điện thoại cùng Wi-Fi

1. Nhấp đúp `run_lan_phone.bat` trên PC.
2. Script hiển thị IPv4 của PC.
3. Trên điện thoại cùng Wi-Fi, mở `http://IP_CUA_PC:8501`.
4. Nếu Windows Firewall hỏi, cho phép Python/Streamlit trên mạng Private.

## Chấm điểm

- Thiên thời: 20 điểm.
- Nhà nước chi phối: 15 điểm + hard-gate >50%.
- Lãnh đạo: 20 điểm + hard-gate.
- Tài sản ẩn: 15 điểm + hard-gate mặc định.
- Tăng trưởng & biên lợi nhuận: 20 điểm + hard-gate.
- Cổ tức: 10 điểm, ưu tiên.

## Kiểm thử

```bash
set PYTHONPATH=.
pytest -q
```

V3 hiện có **14 test**, bao gồm scoring, hard-gate >50%, provider helpers, PDF miner, Watchlist, chuẩn hóa OHLCV, chỉ số giá và cache SQLite.

## Lưu ý

- App là công cụ nghiên cứu và tổ chức dữ liệu, không tự đặt lệnh.
- Giá/khối lượng từ API bên thứ ba có thể có độ trễ hoặc gián đoạn; luôn xem ngày phiên mới nhất hiển thị trên chart.
- Các kết luận về tài sản ẩn, quản trị, sở hữu và định giá phải được kiểm chứng bằng CBTT, BCTC kiểm toán và tài liệu gốc.
