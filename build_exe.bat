@echo off
setlocal
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYV=%%v
echo Python detecte : %PYV%
for /f "tokens=1,2 delims=." %%a in ("%PYV%") do (
  set MAJ=%%a
  set MIN=%%b
)
if not "%MAJ%"=="3" goto badpy
if %MIN% LSS 10 goto badpy
if %MIN% GTR 12 goto badpy
goto okpy

:badpy
echo.
echo ERREUR : Python 3.10, 3.11 ou 3.12 est requis (pas 3.13 ou plus).
echo Installe Python 3.12 depuis python.org, puis relance ce fichier.
pause
exit /b 1

:okpy
python -m pip install --upgrade pip
python -m pip install llama-cpp-python --only-binary=llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 goto fail
python -c "import llama_cpp; print('Moteur IA OK', llama_cpp.__version__)"
if errorlevel 1 goto fail
python -m pip install -r requirements.txt
if errorlevel 1 goto fail
python -m PyInstaller --noconfirm --onefile --windowed --collect-all llama_cpp --name AI_Assistant_Hybride main.py
if errorlevel 1 goto fail
if not exist dist\models mkdir dist\models
echo.
echo EXE cree dans dist\AI_Assistant_Hybride.exe
echo Le modele IA (~400 Mo) sera telecharge au 1er lancement, ou place un fichier .gguf dans dist\models
pause
exit /b 0

:fail
echo.
echo ERREUR : la compilation a echoue (voir les messages ci-dessus). Aucun EXE valide n'a ete cree.
pause
exit /b 1
