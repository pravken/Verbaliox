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

rem --- uv: on PATH, where its installers put it (winget may leave it in its own package folder when it
rem --- cannot make the shortcut in WinGet\Links), else installed: winget first, then the installer of
rem --- astral.sh. Their output goes to the log, so a failure says why
call :find_uv
if not defined UV (
    echo ##STEP uv
    echo [0/2] Installing uv package manager...
    winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    call :find_uv
)
if not defined UV (
    echo       winget did not give uv: the installer from astral.sh
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://astral.sh/uv/install.ps1 | iex"
    call :find_uv
)
if defined UV echo       uv: !UV!

set "SIGNED_PY="
if not "%SAC%"=="0" call :find_signed_python
if not "%SAC%"=="0" if not defined SIGNED_PY (
    echo ##STEP python
    echo [0/2] Smart App Control is on: installing Python 3.11 from python.org ^(signed^)...
    winget install --id=Python.Python.3.11 -e --scope user --accept-source-agreements --accept-package-agreements
    call :find_signed_python
)
if not "%SAC%"=="0" call :sac_warning

if defined UV (
    echo ##STEP venv
    echo [1/2] Creating Python 3.11 virtual environment via uv...
    if exist ".venv\Scripts\python.exe" (
        echo       .venv exists: updating its libraries
    ) else if defined SIGNED_PY (
        echo       Python: !SIGNED_PY!
        "!UV!" venv .venv --python "!SIGNED_PY!"
    ) else (
        rem Prefer a uv-managed Python: the Microsoft Store Python virtualizes AppData and hides files from other programs
        "!UV!" venv .venv --python 3.11 --python-preference only-managed || "!UV!" venv .venv --python 3.11
    )
    if not exist ".venv\Scripts\python.exe" goto :uv_venv_failed
    echo ##STEP packages
    echo [2/2] Installing dependencies via uv...
    rem requirements.txt is an exact lock with SHA-256 hashes (see requirements.in)
    "!UV!" pip install --python ".venv\Scripts\python.exe" -r requirements.txt --require-hashes --index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cu126
    if errorlevel 1 goto :install_failed
    goto :done
)

rem --- uv could not make .venv (its Python may be blocked on this PC): Python 3.11 and pip instead
:uv_venv_failed
echo       uv could not create .venv: trying Python 3.11 and pip
if exist ".venv" rmdir /s /q .venv

rem --- Without uv: pip of a Python 3.11 (the libraries are locked for 3.11). Any other "python" on PATH,
rem --- a Python 2.7 say, is never taken; missing, Python 3.11 of python.org is installed
echo ##STEP venv
echo [1/2] Creating Python virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo       .venv exists: updating its libraries
) else (
    set "PY311=!SIGNED_PY!"
    if not defined PY311 call :find_py311
    if not defined PY311 (
        echo ##STEP python
        echo       Python 3.11 not found: installing it from python.org...
        winget install --id=Python.Python.3.11 -e --scope user --accept-source-agreements --accept-package-agreements
        call :find_py311
    )
    if not defined PY311 goto :no_python
    echo       Python: !PY311!
    "!PY311!" -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto :venv_failed
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

rem --- Neither uv nor Python 3.11 could be had: said plainly instead of failing step after step
:no_python
echo.
echo ==============================================================
echo   Neither uv nor Python 3.11 could be installed (see above).
echo   Install Python 3.11 from python.org or uv from astral.sh,
echo   then start Verbaliox again.
echo ==============================================================
if not defined QUIET pause
exit /b 1

:venv_failed
echo.
echo ==============================================================
echo   The Python environment .venv could not be created (see above).
echo ==============================================================
if not defined QUIET pause
exit /b 1

rem --- A new environment half installed would look ready to the launcher and fail at start: it is
rem --- removed, so the next start runs the setup again
:install_failed
echo.
echo ==============================================================
echo   Installing the libraries failed (see the messages above).
echo   Check the internet connection and run setup.bat again.
echo ==============================================================
rem An environment that was there before stays: its mark is still the old one, so the next start
rem tries the update again
if not defined UPDATE if exist .venv rmdir /s /q .venv
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

rem --- uv: on PATH, in the folders its installers use, or in the package folder of winget. A uv that
rem --- does not start is skipped: on a work PC a policy may forbid programs in AppData ("The system
rem --- cannot execute the specified program")
:find_uv
set "UV="
for /f "delims=" %%u in ('where uv 2^>nul') do call :try_uv "%%u"
for %%p in ("%USERPROFILE%\.local\bin\uv.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" "%USERPROFILE%\.cargo\bin\uv.exe") do call :try_uv "%%~p"
for /d %%d in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv*") do call :try_uv "%%~d\uv.exe"
goto :eof

:try_uv
if defined UV goto :eof
if not exist "%~1" goto :eof
"%~1" --version >nul 2>nul
if not errorlevel 1 set "UV=%~1"
if not defined UV echo       uv does not start here, skipped: %~1
goto :eof

rem --- A Python 3.11 (never 2.7 or another 3.x: the libraries are locked for 3.11), not the Store one
:find_py311
set "PY311="
call :find_signed_python
if defined SIGNED_PY set "PY311=!SIGNED_PY!"
if defined PY311 goto :eof
for /f "delims=" %%p in ('python -c "import sys; sys.version_info[:2] == (3, 11) and print(sys.executable)" 2^>nul') do (
    echo %%p | find /i "WindowsApps" >nul || set "PY311=%%p"
)
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
