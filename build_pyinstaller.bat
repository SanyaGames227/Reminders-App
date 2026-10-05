@echo off
cd /d "%~dp0"
python -m pip install -q pyinstaller PyQt5 || goto :err
if not exist ".reminders-data\icon.ico" python icons.py ".reminders-data\icon.ico"
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name Reminders ^
  --distpath dist-pyinstaller ^
  --workpath build-pyinstaller ^
  --icon ".reminders-data\icon.ico" ^
  --exclude-module tkinter ^
  main.pyw || goto :err
echo.
echo Done: dist-pyinstaller\Reminders\Reminders.exe
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
