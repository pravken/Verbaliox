@echo off
cd /d "%~dp0"

echo ==============================================================
echo   Verbaliox - optional Translate ^& Dub environment (.venv-dub)
echo   VoxCPM2 TTS (Apache-2.0) + Demucs (MIT), ~6 GB
echo ==============================================================

set "DUBPY=.venv-dub\Scripts\python.exe"
set "TORCH_INDEX=https://download.pytorch.org/whl/cu126"
rem uv where setup.bat found or installed it, also when it is not on PATH (setup.bat :find_uv)
call :find_uv

rem An environment made on Python 3.10 before: the lock is for 3.11 now, it is made again
if exist "%DUBPY%" (
    "%DUBPY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || rmdir /s /q .venv-dub
)
rem An environment made for Chatterbox (before 0.6.0): made again, so none of its packages stay
if exist ".venv-dub\Lib\site-packages\chatterbox" rmdir /s /q .venv-dub
if not exist "%DUBPY%" (
    if defined UV ("%UV%" venv .venv-dub --python 3.11 --python-preference only-managed || "%UV%" venv .venv-dub --python 3.11)
)
if not exist "%DUBPY%" (
    py -3.11 -m venv .venv-dub
)
if not exist "%DUBPY%" (
    echo Could not create .venv-dub. Install Python 3.11 or run setup.bat first.
    exit /b 1
)

if defined UV (
    "%UV%" pip install --python "%DUBPY%" --require-hashes -r requirements-dub.txt --extra-index-url %TORCH_INDEX% --index-strategy unsafe-best-match && "%UV%" pip install --python "%DUBPY%" --no-deps --require-hashes -r requirements-dub-voxcpm.txt && goto :done
)
"%DUBPY%" -m pip install --require-hashes -r requirements-dub.txt --extra-index-url %TORCH_INDEX%
"%DUBPY%" -m pip install --no-deps --require-hashes -r requirements-dub-voxcpm.txt

:done
echo.
echo Done. Model weights (~5 GB) are downloaded on the first dubbing job into models\dub.
goto :eof

rem --- uv: on PATH, in the folders its installers use, or in the package folder of winget
:find_uv
set "UV="
for /f "delims=" %%u in ('where uv 2^>nul') do if not defined UV set "UV=%%u"
for %%p in ("%USERPROFILE%\.local\bin\uv.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" "%USERPROFILE%\.cargo\bin\uv.exe") do (
    if not defined UV if exist "%%~p" set "UV=%%~p"
)
for /d %%d in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv*") do (
    if not defined UV if exist "%%~d\uv.exe" set "UV=%%~d\uv.exe"
)
goto :eof
