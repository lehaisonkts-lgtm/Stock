@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install -U pip
python -m pip install --extra-index-url https://vnstocks.com/api/simple -r requirements.txt
ipconfig | findstr /i "IPv4"
echo.
echo Mo tren dien thoai cung Wi-Fi: http://DIA_CHI_IPV4_CUA_PC:8501
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
