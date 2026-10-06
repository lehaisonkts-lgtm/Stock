@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install -U pip
python -m pip install --extra-index-url https://vnstocks.com/api/simple -r requirements.txt
python -m streamlit run app.py
