# UI / UX map — State Value Screener VN V3

## Mục tiêu

Giao diện bám quy trình nghiên cứu: tạo universe → lọc → xem hành vi giá/khối lượng → kiểm chứng BCTC → phân tích sâu → quản lý Watchlist.

## Điều hướng chính

1. **Tổng quan** — KPI, Top candidates và việc còn thiếu.
2. **Sàng lọc & xếp hạng** — mô hình 6 tiêu chí.
3. **Quét sở hữu Nhà nước** — universe >50%.
4. **Biểu đồ giá & khối lượng** — nến ngày OHLC + volume + MA + cache.
5. **Phân tích doanh nghiệp** — drill-down một mã.
6. **Soi BCTC & tài sản ẩn** — PDF và bằng chứng.
7. **Watchlist & luận điểm** — pipeline nghiên cứu.
8. **Dữ liệu & cấu hình** — override, registry, benchmark, mã bắt buộc, backup.
9. **Lịch sử & mô hình** — audit trail và cách chấm điểm.

## Màn hình chart

- Mã bắt buộc được ghim trước: CKA, KSV, CSV, VEA, TMB, CST, HU4, HUD, HD8, L14, CLM, FT1, FOX.
- Có ô nhập mã khác.
- Range selector 1M/3M/6M/1Y/3Y/5Y/MAX.
- Toggle MA20/MA50/Volume MA20.
- KPI phiên mới nhất nằm trên chart.
- Nến ở panel trên; volume ở panel dưới, dùng chung trục thời gian.
- Bảng raw OHLCV nằm trong expander để không làm rối màn hình chính.
- Có cập nhật live và fallback SQLite.
- Batch update 13 mã bắt buộc có progress và trạng thái từng mã.

## Nguyên tắc

- Tone trắng + navy + xanh tài chính.
- Responsive trên điện thoại.
- Dữ liệu, bằng chứng và giả định luôn tách riêng.
- Không biến chỉ báo kỹ thuật thành tín hiệu mua/bán tự động.
- Mọi chart luôn hiển thị **phiên dữ liệu mới nhất** và **nguồn**.

## Luồng nghiên cứu

`Universe >50%` → `Screener` → `Price/Volume` → `Single-company research` → `PDF hidden assets` → `Watchlist` → `Periodic review`
