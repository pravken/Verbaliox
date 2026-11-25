@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
rem What uv downloads (its package cache, the Python it installs) stays in the program folder, not on
rem the system disk: the Python is not in AppData either, where a company policy may block programs
set "UV_CACHE_DIR=%~dp0.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%~dp0python"
rem /quiet: started by the setup window of Verbaliox.exe, which shows the "##STEP" lines as its progress
rem and the rest in its log; no pause at the end. An existing .venv is kept and its libraries are
rem brought to requirements.txt (a newer version installed over an older one)
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"
set "UPDATE="
if exist ".venv\Scripts\python.exe" set "UPDATE=1"
rem The program folder moved (another drive, a renamed user folder): the environment still points at the
rem Python of the old place and does not run. Its link is mended when that Python came with the program;
rem otherwise the environment is made again (found in the audit: setup ended in "failed")
if defined UPDATE (
    call :venv_runs
    if not defined VENV_OK call :venv_relink
    if not defined VENV_OK (
        echo       The environment belongs to another folder: it is made again
        rmdir /s /q ".venv"
        set "UPDATE="
    )
)

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
rem --- cannot make the shortcut in WinGet\Links), else installed: winget first, then the release archive
rem --- of uv from GitHub, a pinned version checked by its SHA-256 (never a script run from the internet),
rem --- unpacked into the program folder. Their output goes to the log, so a failure says why
set "UV_ZIP_URL=https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip"
set "UV_ZIP_SHA256=0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021"
set "UV_DIR=%~dp0.uv"
call :find_uv
if not defined UV (
    echo ##STEP uv
    echo [0/2] Installing uv package manager...
    winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    call :find_uv
)
if not defined UV (
    echo       winget did not give uv: the uv release archive from GitHub
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; $z = $env:UV_DIR + '-download.zip'; Invoke-WebRequest -UseBasicParsing -Uri $env:UV_ZIP_URL -OutFile $z; if ((Get-FileHash -Algorithm SHA256 -LiteralPath $z).Hash -ne $env:UV_ZIP_SHA256) { Remove-Item -LiteralPath $z; throw 'uv archive: SHA-256 does not match, not unpacked' }; Expand-Archive -Force -LiteralPath $z -DestinationPath $env:UV_DIR; Remove-Item -LiteralPath $z"
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
        "!UV!" venv .venv --python 3.11 --python-preference only-managed
        if not exist ".venv\Scripts\python.exe" call :managed_venv
        if not exist ".venv\Scripts\python.exe" "!UV!" venv .venv --python 3.11
    )
    rem The Python of the environment must run: a policy that blocks programs in AppData blocks the
    rem Python uv downloads there too. Then the pip way below makes it on Python 3.11 of python.org
    call :venv_runs
    if not defined VENV_OK (
        echo       uv could not make a working environment: Python 3.11 and pip instead
        if not defined UPDATE if exist .venv rmdir /s /q .venv
        set "UV="
    )
)
if defined UV (
    echo ##STEP packages
    echo [2/2] Installing dependencies via uv...
    rem requirements.txt is an exact lock with SHA-256 hashes (see requirements.in)
    "!UV!" pip install --python ".venv\Scripts\python.exe" -r requirements.txt --require-hashes --index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cu126
    if errorlevel 1 goto :install_failed
    goto :done
)

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
call :venv_runs
if not defined VENV_OK goto :venv_failed
echo ##STEP packages
echo [2/2] Installing dependencies via pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt --require-hashes --extra-index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 goto :install_failed

:done
rem The packages are in the environment now: their downloads go (gigabytes)
if exist ".uv-cache" rmdir /s /q ".uv-cache"
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
echo   The Python environment .venv could not be created or does not run
echo   (see above). A company policy may block programs in AppData:
echo   install Python 3.11 from python.org and run setup.bat again.
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
rem A path is compared as text, not piped to find: a pipe reads it as a command line again
for /f "delims=" %%p in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    set "CAND=%%p"
    if "!CAND:WindowsApps=!"=="!CAND!" set "SIGNED_PY=%%p"
)
goto :eof

rem --- uv: on PATH, in the folders its installers use (the program folder's .uv: the archive above),
rem --- or in the package folder of winget
:find_uv
set "UV="
for /f "delims=" %%u in ('where uv 2^>nul') do call :try_uv "%%u"
for %%p in ("%UV_DIR%\uv.exe" "%USERPROFILE%\.local\bin\uv.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" "%USERPROFILE%\.cargo\bin\uv.exe") do call :try_uv "%%~p"
for /d %%d in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv*") do call :try_uv "%%~d\uv.exe"
goto :eof

rem --- A uv is taken only if it runs: the shortcut winget leaves may point nowhere, or a policy may
rem --- block programs in AppData ("The system cannot execute the specified program")
:try_uv
if defined UV goto :eof
if not exist "%~1" goto :eof
"%~1" --version >nul 2>nul
if errorlevel 1 (
    echo       uv at %~1 does not run: skipped
    goto :eof
)
set "UV=%~1"
goto :eof

rem --- uv downloaded its Python but Windows refused the link uv makes to it inside the program folder
rem --- ("untrusted mount point", os error 448): the environment is made by that Python itself, by its full
rem --- path, instead of falling back to another Python of the system
:managed_venv
set "MANAGED_PY="
for /d %%d in ("%~dp0python\cpython-3.11.*-windows-x86_64-none") do if exist "%%~d\python.exe" set "MANAGED_PY=%%~d\python.exe"
if not defined MANAGED_PY goto :eof
echo       uv could not link its Python ^(a Windows restriction^): the environment from !MANAGED_PY!
if exist .venv rmdir /s /q .venv
"!MANAGED_PY!" -m venv .venv
goto :eof

rem --- The environment's Python runs (it exists and is not blocked)
:venv_relink
set "MOVED_PY="
for /d %%d in ("%~dp0python\cpython-3.11*") do if exist "%%~fd\python.exe" set "MOVED_PY=%%~fd"
if not defined MOVED_PY goto :eof
echo       The program folder moved: the environment is linked to !MOVED_PY!
set "VS_HOME=!MOVED_PY!"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f = '.venv\pyvenv.cfg'; $t = [IO.File]::ReadAllText($f); $t = [Text.RegularExpressions.Regex]::Replace($t, '(?m)^home\s*=.*$', 'home = ' + $env:VS_HOME); [IO.File]::WriteAllText($f, $t, (New-Object Text.UTF8Encoding $false))"
call :venv_runs
goto :eof

:venv_runs
set "VENV_OK="
if not exist ".venv\Scripts\python.exe" goto :eof
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo       The Python of .venv does not run
    goto :eof
)
set "VENV_OK=1"
goto :eof

rem --- A Python 3.11 (never 2.7 or another 3.x: the libraries are locked for 3.11), not the Store one
:find_py311
set "PY311="
call :find_signed_python
if defined SIGNED_PY set "PY311=!SIGNED_PY!"
if defined PY311 goto :eof
for /f "delims=" %%p in ('python -c "import sys; sys.version_info[:2] == (3, 11) and print(sys.executable)" 2^>nul') do (
    set "CAND=%%p"
    if "!CAND:WindowsApps=!"=="!CAND!" set "PY311=%%p"
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
