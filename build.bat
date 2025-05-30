@echo off
echo Installing requirements...
pip install -r requirements.txt

echo Building executable...
pyinstaller --onefile ^
    --noconsole ^
    --name "TikTok Lite" ^
    --icon "media\logo.ico" ^
    main.py

echo Build complete! The executable can be found in the dist folder.
pause