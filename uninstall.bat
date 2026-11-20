@echo off
rem Verbaliox: removes the program and everything it made on this computer (uninstall.ps1 says what).
rem uninstall.bat -Yes                 no questions: the program, its data and models
rem uninstall.bat -KeepData            keeps recordings, transcripts and settings
rem uninstall.bat -WithOllama -WithUv -WithPython   also the tools setup installed (other programs may use them)
chcp 65001 >nul
set "VX_UNINSTALL=%~dp0uninstall.ps1"
cd /d "%TEMP%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%VX_UNINSTALL%" %*
rem A failure (a company policy that forbids scripts, a folder that is not Verbaliox) stays on the screen
rem instead of the window flashing away (found in the audit)
if errorlevel 1 (
    echo.
    echo Verbaliox was not removed ^(error %errorlevel%^). If scripts are forbidden on this computer, ask the administrator.
    pause
)
