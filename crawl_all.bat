@echo off
echo ========================================
echo  Radar BDS - Crawl Guland + BatDongSan
echo ========================================
cd /d "%~dp0"

echo.
echo [1/2] Cai thu vien Playwright...
pip install playwright -q
playwright install chromium

echo.
echo [2/2] Chay full crawl...
python radar.py crawl-all

echo.
echo ========================================
echo  XONG! Kiem tra: python radar.py query --stats
echo ========================================
pause
