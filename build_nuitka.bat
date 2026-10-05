@echo off
cd /d "%~dp0"
python -m pip install -q nuitka ordered-set zstandard PyQt5 || goto :err
if not exist ".reminders-data\icon.ico" python icons.py ".reminders-data\icon.ico"
python -m nuitka --standalone ^
  --enable-plugin=pyqt5 ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=".reminders-data\icon.ico" ^
  --include-qt-plugins=sensible,styles ^
  --output-filename=Reminders.exe ^
  --output-dir=dist-nuitka ^
  --assume-yes-for-downloads ^
  --remove-output ^
  --nofollow-import-to=tkinter ^
  main.pyw || goto :err
echo.
echo Done: dist-nuitka\main.dist\Reminders.exe
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
