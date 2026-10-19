@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PC Hub - build
echo.
echo  ===  PC Hub: build exe + installer  ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [X] Python non trovato. Installa Python 3.11+ da python.org ^(spunta "Add to PATH"^).
  goto :error
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creo l'ambiente virtuale...
  %PY% -m venv .venv || goto :error
)
set "VPY=.venv\Scripts\python.exe"

echo [2/5] Installo le dipendenze...
"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install -r requirements-dev.txt --quiet || goto :error

echo [3/5] Preparo icona e info versione...
"%VPY%" tools\make_icon.py || goto :error
"%VPY%" tools\write_version_info.py || goto :error
for /f "usebackq delims=" %%v in (`"%VPY%" -c "import pchub;print(pchub.VERSION)"`) do set "APPVERSION=%%v"

echo [4/5] Creo l'exe con PyInstaller...
"%VPY%" -m PyInstaller --noconfirm --clean build\pchub.spec --distpath dist --workpath build\work || goto :error

echo [5/5] Creo l'installer con Inno Setup...
call :findIscc
if not defined ISCC (
  echo Inno Setup non trovato: provo a installarlo con winget...
  winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
  call :findIscc
)
if not defined ISCC (
  echo [!] Inno Setup 6 non disponibile. Installalo da https://jrsoftware.org/isdl.php e rilancia build.bat
  echo     L'app funziona comunque da: dist\PC Hub\PC Hub.exe
  goto :end
)
"%ISCC%" /Qp /DAppVersion=%APPVERSION% build\installer.iss || goto :error
echo.
echo  Fatto!  Installer:  dist\installer\PCHub-Setup-%APPVERSION%.exe
echo.
goto :end

:findIscc
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
exit /b 0

:error
echo.
echo  [X] Build fallita. Leggi i messaggi qui sopra.
pause
exit /b 1

:end
pause
exit /b 0
