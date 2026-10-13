@echo off
rem Construit l'application Windows et son installateur, en une seule commande :
rem   1. environnement Python (.venv) et dependances
rem   2. telechargement du build statique de ffmpeg (epingle, SHA-256 verifie)
rem   3. PyInstaller (onedir)     -> dist\FileConverter\
rem   4. Inno Setup               -> dist\installer\FileConverter-Setup-<version>.exe
rem Prerequis : Python 3.10+ (lanceur "py") et Inno Setup 6 (winget install JRSoftware.InnoSetup).

setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "FFMPEG_DIR=%~dp0build\ffmpeg"

echo [1/4] Environnement Python
if not exist "%PY%" (
    where py >nul 2>&1 || goto :no_python
    py -3 -m venv .venv || goto :fail
)
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-build.txt || goto :fail

echo [2/4] ffmpeg
"%PY%" packaging\fetch_ffmpeg.py "%FFMPEG_DIR%" || goto :fail

echo [3/4] PyInstaller
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build\pyinstaller packaging\FileConverter.spec || goto :fail

echo [4/4] Inno Setup
call :find_iscc
if not defined ISCC goto :no_iscc
"%ISCC%" /Q packaging\installer.iss || goto :fail

echo.
echo Termine :
echo   Application  : dist\FileConverter\FileConverter.exe
for %%F in (dist\installer\FileConverter-Setup-*.exe) do echo   Installateur : %%F
exit /b 0

:find_iscc
set "ISCC="
for %%I in (ISCC.exe) do if not "%%~$PATH:I"=="" set "ISCC=%%~$PATH:I"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
exit /b 0

:no_python
echo ERREUR : Python 3.10+ introuvable. Installez-le depuis https://www.python.org/downloads/
exit /b 1

:no_iscc
echo ERREUR : Inno Setup 6 introuvable. Installez-le avec : winget install JRSoftware.InnoSetup
exit /b 1

:fail
echo.
echo ERREUR : la construction a echoue, voir les messages ci-dessus.
exit /b 1
