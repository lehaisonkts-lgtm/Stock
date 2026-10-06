# Deploy SONLEE STOCK — GitHub Private + Streamlit Community Cloud

## Mục tiêu
- Source code: chỉ chủ repo GitHub Private xem/sửa.
- App: public qua link `https://stock-sonlee.streamlit.app` nếu subdomain còn trống.
- Viewer: xem dashboard, sàng lọc, sở hữu Nhà nước, biểu đồ OHLCV, phân tích doanh nghiệp.
- Admin: thêm quyền Soi BCTC, Watchlist gốc, dữ liệu/cấu hình, lịch sử/mô hình bằng mật khẩu server-side.

## 1. Tạo GitHub repository Private
Tên gợi ý: `sonlee-stock`.
Upload toàn bộ nội dung thư mục này lên nhánh `main`.
Không upload `.streamlit/secrets.toml`, file `.db`, `.env`, backup hay file nhạy cảm. `.gitignore` đã chặn sẵn.

## 2. Kết nối Streamlit Community Cloud với GitHub
Vào `https://share.streamlit.io`, kết nối GitHub và cấp quyền truy cập private repositories.
Chọn **Create app** > repository `sonlee-stock` > branch `main` > entrypoint `streamlit_app.py`.

## 3. Chọn URL
Trong `App URL`, nhập `stock-sonlee` nếu còn khả dụng.
Kết quả: `https://stock-sonlee.streamlit.app`.
`stock-sonlee.app` là domain riêng, không phải URL miễn phí mặc định của Community Cloud.

## 4. Cấu hình Secrets
Trong phần Advanced settings / Secrets, thêm:

```toml
ADMIN_PASSWORD = "mat-khau-rat-dai-va-rieng-cua-anh"
```

Không ghi mật khẩu này vào GitHub.

## 5. Public app nhưng private source
Sau khi deploy, vào App settings > Sharing > đặt app thành **public**.
Repository vẫn giữ **Private**.

## 6. Cập nhật code
Mỗi lần push commit mới lên `main`, Streamlit Community Cloud sẽ tự triển khai phiên bản mới.

## 7. Lưu ý dữ liệu
Community Cloud không bảo đảm dữ liệu ghi vào filesystem local tồn tại vĩnh viễn. SQLite trong app phù hợp cache/tạm thời. Nếu cần Watchlist/ghi chú/override lưu bền vững giữa các lần reboot, chuyển sang Postgres/Supabase/Neon ở V5.
