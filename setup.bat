@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
rem /quiet: started by the setup window of Verbaliox.exe, which shows the "##STEP" lines as its progress
rem and the rest in its log; no pause at the end. An existing .venv is kept and its libraries are
rem brought to requirements.txt (a newer version installed over an older one)
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"
set "UPDATE="
if exist ".venv\Scripts\python.exe" set "UPDATE=1"

echo ==============================================================
echo   Verbaliox - First-Run Environment Setup
echo ==============================================================

rem --- Smart App Control (Windows 11) blocks program files without a digital signature. The Python
rem --- that uv downloads is not signed, the one from python.org is: with Smart App Control on, the
rem --- environment is built on the python.org Python.
set "SAC=0"
for /f "tokens=3" %%v in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy" /v VerifiedAndReputablePolicyState 2^>nul ^| find "VerifiedAndReputablePolicyState"') do set "SAC=%%v"
if "%SAC%"=="0x0" set "SAC=0"
if "%SAC%"=="0x1" set "SAC=1"
if "%SAC%"=="0x2" set "SAC=2"

rem --- uv: winget first, then the official installer from astral.sh (winget is missing on some PCs
rem --- or fails without a word). Without uv the environment is made with Python 3.11 and pip
where uv >nul 2>nul
if not errorlevel 1 goto :have_uv
echo ##STEP uv
echo [0/2] Installing uv package manager...
where winget >nul 2>nul
if errorlevel 1 (
    echo       winget is not available on this PC
) else (
    winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements --disable-interactivity >nul 2>nul
    if errorlevel 1 echo       winget could not install uv ^(code !ERRORLEVEL!^)
)
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where uv >nul 2>nul
if not errorlevel 1 goto :have_uv
echo       Installing uv with its installer from astral.sh...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://astral.sh/uv/install.ps1 | iex"
where uv >nul 2>nul
if errorlevel 1 echo       uv could not be installed: the environment is made with Python 3.11 and pip
:have_uv

set "SIGNED_PY="
if not "%SAC%"=="0" call :find_signed_python
if not "%SAC%"=="0" if not defined SIGNED_PY (
    echo ##STEP python
    echo [0/2] Smart App Control is on: installing Python 3.11 from python.org ^(signed^)...
    winget install --id=Python.Python.3.11 -e --scope user --accept-source-agreements --accept-package-agreements >nul 2>nul
    call :find_signed_python
)
if not "%SAC%"=="0" call rem --- Python 3.11 for the pip way: python.org (as above), then "python" on PATH only if it is 3.11
:find_python311
set "PY311="
if defined SIGNED_PY (
    set "PY311=!SIGNED_PY!"
    goto :eof
)
call :find_signed_python
if defined SIGNED_PY (
    set "PY311=!SIGNED_PY!"
    goto :eof
)
for /f "delims=" %%p in ('python -c "import sys; sys.stdout.write(sys.executable if sys.version_info[:2] == (3, 11) else '')" 2^>nul') do set "PY311=%%p"
goto :eof

:sac_warning

where uv >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo ##STEP venv
    echo [1/2] Creating Python 3.11 virtual environment via uv...
    if exist ".venv\Scripts\python.exe" (
        echo       .venv exists: updating its libraries
    ) else if defined SIGNED_PY (
        echo       Python: !SIGNED_PY!
        uv venv .venv --python "!SIGNED_PY!"
    ) else (
        rem Prefer a uv-managed Python: the Microsoft Store Python virtualizes AppData and hides files from other programs
        uv venv .venv --python 3.11 --python-preference only-managed || uv venv .venv --python 3.11
    )
    if not exist ".venv\Scripts\python.exe" goto :venv_failed
    echo ##STEP packages
    echo [2/2] Installing dependencies via uv...
    rem requirements.txt is an exact lock with SHA-256 hashes (see requirements.in)
    uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt --require-hashes --index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cu126
    if errorlevel 1 goto :install_failed
    goto :done
)

echo ##STEP venv
echo [1/2] Creating Python virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo       .venv exists: updating its libraries
    goto :pip_packages
)
rem The packages are locked for Python 3.11: any other Python on PATH ^(an old 2.7, a newer 3.x^) is
rem never used. Without one, Python 3.11 is installed from python.org with winget
call :find_python311
if not defined PY311 (
    echo       Python 3.11 not found: installing it from python.org...
    winget install --id=Python.Python.3.11 -e --scope user --accept-source-agreements --accept-package-agreements --disable-interactivity >nul 2>nul
    call :find_python311
)
if not defined PY311 goto :no_python
echo       Python: !PY311!
"!PY311!" -m venv .venv
if not exist ".venv\Scripts\python.exe" goto :venv_failed
:pip_packages
echo ##STEP packages
echo [2/2] Installing dependencies via pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt --require-hashes --extra-index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 goto :install_failed

:done
rem The requirements this environment has (app/pyenv.py REQUIREMENTS_MARK): the launcher compares it
".venv\Scripts\python.exe" -c "import hashlib; open(r'.venv\verbaliox-requirements.sha256', 'w').write(hashlib.sha256(open('requirements.txt', 'rb').read()).hexdigest())"
echo.
echo ==============================================================
echo   Setup complete. Launching Verbaliox...
echo ==============================================================
goto :eof

rem --- A new environment half installed would look ready to the launcher and fail at start: it is
rem --- removed, so the next start runs the setup again
:install_failed
echo.
echo ==============================================================
echo   Installing the libraries failed (see the messages above).
echo   Check the internet connection and run setup.bat again.
echo ==============================================================
goto :failed

:venv_failed
echo.
echo ==============================================================
echo   Creating the Python environment failed ^(see the messages above^).
echo   Check the internet connection and run setup.bat again.
echo ==============================================================
goto :failed

:no_python
echo.
echo ==============================================================
echo   Python 3.11 was not found and could not be installed.
echo   Install Python 3.11 from https://www.python.org/downloads/
echo   or uv from https://docs.astral.sh/uv/ and run setup.bat again.
echo ==============================================================
goto :failed

:failed
rem An environment that was there before stays: its mark is still the old one, so the next start
rem tries the update again
if exist ".venv" if not defined UPDATE rmdir /s /q .venv
if not defined QUIET pause
exit /b 1

rem --- Python 3.11 from python.org: the usual install folders, then the py launcher (never the
rem --- Microsoft Store Python in WindowsApps)
:find_signed_python
for %%p in ("%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python311\python.exe") do (
    if exist "%%~p" (
        set "SIGNED_PY=%%~p"
        goto :eof
    )
)
for /f "delims=" %%p in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    echo %%p | find /i "WindowsApps" >nul || set "SIGNED_PY=%%p"
)
goto :eof

rem --- Python 3.11 for the pip way: python.org (as above), then "python" on PATH only if it is 3.11
:find_python311
set "PY311="
if defined SIGNED_PY (
    set "PY311=!SIGNED_PY!"
    goto :eof
)
call :find_signed_python
if defined SIGNED_PY (
    set "PY311=!SIGNED_PY!"
    goto :eof
)
for /f "delims=" %%p in ('python -c "import sys; sys.stdout.write(sys.executable if sys.version_info[:2] == (3, 11) else '')" 2^>nul') do set "PY311=%%p"
goto :eof

:sac_warning
echo.
echo   ------------------------------------------------------------
echo   Smart App Control is on.
echo   It may block parts of Python libraries that have no digital
echo   signature ^(Windows shows "This app is partially blocked"^).
echo   If Verbaliox does not start or a feature fails, turn it off:
echo   Windows Security - App ^& browser control - Smart App Control
echo   settings - Off. It cannot be turned back on without
echo   reinstalling Windows; Defender keeps protecting the PC.
echo   ------------------------------------------------------------
echo.
goto :eof
