@echo off
set SCREENER_PORT=8080
echo.
echo  Exporting latest data to frontend...
set PYTHONPATH=.
python pipeline/export_static.py
echo.
echo  Starting screener on http://localhost:8080
echo  Opening browser...
echo.
start http://localhost:8080
python run.py serve
echo.
echo  Server stopped. Press any key to close this window.
pause >nul
