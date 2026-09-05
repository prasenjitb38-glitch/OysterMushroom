@echo off
cd /d "%~dp0"
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --name OysterMushroomManager --add-data "templates;templates" --add-data "static;static" main.py
if errorlevel 1 pause
