@echo off
setlocal
cd /d "%~dp0"
set "HOME_DIR=%LOCALAPPDATA%\HighlightExporter"
set "VENV=%HOME_DIR%\venv"
set "PY=%VENV%\Scripts\python.exe"

if exist "%PY%" goto have_env

echo First run on this computer: setting up. This takes a minute or two.
set "BASEPY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "BASEPY=py -3"
if defined BASEPY goto make_env
python --version >nul 2>&1
if not errorlevel 1 set "BASEPY=python"
if defined BASEPY goto make_env
echo.
echo Python is not installed on this computer. Install it once from
echo https://www.python.org/downloads/  (tick "Add python.exe to PATH"), then run this again.
pause
exit /b 1

:make_env
if not exist "%HOME_DIR%" mkdir "%HOME_DIR%"
%BASEPY% -m venv "%VENV%"
if errorlevel 1 goto env_fail

:have_env
fc /b "%~dp0requirements.txt" "%HOME_DIR%\requirements.installed" >nul 2>&1
if not errorlevel 1 goto run
echo Installing the packages this tool needs...
"%PY%" -m pip install --quiet --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto pip_fail
copy /y "%~dp0requirements.txt" "%HOME_DIR%\requirements.installed" >nul

:run
"%PY%" -m highlight_export %*

:again_prompt
echo.
choice /c YN /n /m "Run again? Press Y to export more PDFs, or N to close: "
if errorlevel 2 exit /b 0
echo.
"%PY%" -m highlight_export
goto again_prompt

:env_fail
echo.
echo Could not set up the Python environment. Please tell whoever set this tool up.
pause
exit /b 1

:pip_fail
echo.
echo The package install failed. Check the internet connection and run this again.
pause
exit /b 1
