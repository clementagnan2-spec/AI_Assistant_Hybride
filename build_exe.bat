@echo off
python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name AI_Assistant_Hybride main.py
echo EXE cree dans dist\\AI_Assistant_Hybride.exe
pause
