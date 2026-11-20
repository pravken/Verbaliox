<#
  Verbaliox: full removal of the program and everything it made on this computer, for a portable folder and
  for an installed copy alike. Started by uninstall.bat (double-click) or:

    powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1 [-Yes] [-KeepData] [-WithOllama] [-WithUv] [-WithPython]

  What is removed:
    - the program folder (the script's folder): the program, its Python environments, caches and the models;
    - the data folder (%LOCALAPPDATA%\Verbaliox, or VERBALIOX_DATA_DIR): recordings kept by the program,
      transcripts, settings, saved API keys, logs; the folders of the old name VerbaScribe and of migrations;
    - «Start with Windows», the uninstall entry of the installer, the Start menu and desktop shortcuts,
      OLLAMA_MODELS when it points into the program's models, the program's temporary files.
  Asked separately (not removed with -Yes unless named): Ollama (-WithOllama), uv (-WithUv), Python 3.11 that
  setup installed (-WithPython): other programs may use them.
  Never removed: a recordings folder chosen in the settings outside the data folder, files imported without a
  copy, exports, notes in the Obsidian vault, backup archives.
#>
param(
    [switch]$Yes,          # no questions: the program, its data and models (not the shared tools)
    [switch]$KeepData,     # keep the data folder (recordings, transcripts, settings)
    [switch]$WithOllama,
    [switch]$WithUv,
    [switch]$WithPython,
    [string]$AppDir = "",  # set when the script runs from a copy in %TEMP%
    [switch]$FromTemp
)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

if (-not $AppDir) { $AppDir = $PSScriptRoot }
$AppDir = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\')

# The program folder holds this script: it runs from a copy in %TEMP%, so the folder can be deleted
if (-not $FromTemp) {
    $copy = Join-Path $env:TEMP "verbaliox-uninstall.ps1"
    Copy-Item -LiteralPath $PSCommandPath -Destination $copy -Force
    $args2 = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $copy, "-AppDir", $AppDir, "-FromTemp")
    if ($Yes) { $args2 += "-Yes" }
    if ($KeepData) { $args2 += "-KeepData" }
    if ($WithOllama) { $args2 += "-WithOllama" }
    if ($WithUv) { $args2 += "-WithUv" }
    if ($WithPython) { $args2 += "-WithPython" }
    Set-Location $env:TEMP
    & powershell.exe @args2
    exit $LASTEXITCODE
}
Set-Location $env:TEMP

# Only a Verbaliox folder: run.py and app\paths.py next to this script (a copy of it elsewhere deletes nothing)
if (-not ((Test-Path -LiteralPath (Join-Path $AppDir "run.py")) -and (Test-Path -LiteralPath (Join-Path $AppDir "app\paths.py")))) {
    Write-Host "Папка $AppDir не похожа на папку Verbaliox (нет run.py и app\paths.py). Ничего не удалено." -ForegroundColor Yellow
    exit 2
}

function Ask([string]$question, [bool]$default = $false) {
    if ($Yes) { return $default }
    $hint = if ($default) { "[Д/н]" } else { "[д/Н]" }
    $answer = Read-Host "$question $hint"
    if (-not $answer) { return $default }
    return $answer.Trim().ToLower() -in @("д", "да", "y", "yes")
}

function Size([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    try {
        $bytes = (Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object -Sum Length).Sum
        if (-not $bytes) { return "" }
        return " ({0:N1} ГБ)" -f ($bytes / 1GB)
    } catch { return "" }
}

function Inside([string]$path, [string]$folder) {
    if (-not $path -or -not $folder) { return $false }
    try {
        $p = [System.IO.Path]::GetFullPath($path).TrimEnd('\') + '\'
        $f = [System.IO.Path]::GetFullPath($folder).TrimEnd('\') + '\'
        return $p.StartsWith($f, [System.StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Is-Protected([string]$path) {
    # never a drive, the user's profile or a system folder, whatever a variable says
    try { $full = [System.IO.Path]::GetFullPath($path).TrimEnd('\') } catch { return $true }
    $guarded = @($env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:TEMP, $env:ProgramFiles, ${env:ProgramFiles(x86)},
                 $env:SystemRoot, [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("MyDocuments"))
    if ($full.Length -le 3) { return $true }
    foreach ($g in $guarded) { if ($g -and $full -ieq $g.TrimEnd('\')) { return $true } }
    return $false
}

function Remove-Folder([string]$path) {
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return }
    if (Is-Protected $path) { Write-Host "  пропускаю ${path}: это не папка программы" -ForegroundColor Yellow; return }
    Write-Host "  удаляю $path"
    for ($i = 0; $i -lt 3; $i++) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $path)) { return }
        Start-Sleep -Seconds 2  # a file still held by a process that is ending
    }
    # a long path or a read-only file: cmd's rd copes with them
    cmd.exe /c "rd /s /q `"$path`"" 2>$null | Out-Null
    if (Test-Path -LiteralPath $path) { Write-Host "  не удалось удалить полностью: $path" -ForegroundColor Yellow }
}

$local = $env:LOCALAPPDATA
$defaultData = Join-Path $local "Verbaliox"
$customData = [Environment]::GetEnvironmentVariable("VERBALIOX_DATA_DIR", "User")
if (-not $customData) { $customData = $env:VERBALIOX_DATA_DIR }
$customModels = [Environment]::GetEnvironmentVariable("VERBALIOX_MODELS_DIR", "User")
if (-not $customModels) { $customModels = $env:VERBALIOX_MODELS_DIR }

$dataDirs = @($defaultData, (Join-Path $local "VerbaScribe"), (Join-Path $local "Verbaliox.migrating"))
$dataDirs += @(Get-ChildItem -LiteralPath $local -Directory -Filter "Verbaliox.before-rename-*" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$dataDirs += @(Get-ChildItem -Path (Join-Path $local "Packages\PythonSoftwareFoundation.Python.*\LocalCache\Local\VerbaScribe") -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$dataDirs = @($dataDirs | Where-Object { Test-Path -LiteralPath $_ })

Write-Host ""
Write-Host "Удаление Verbaliox" -ForegroundColor Cyan
Write-Host ""
Write-Host "Программа: $AppDir$(Size $AppDir)"
if ($KeepData) {
    Write-Host "Данные остаются (-KeepData)."
} else {
    foreach ($d in $dataDirs) { Write-Host "Данные:    $d$(Size $d)" }
}
if ($customData -and (Test-Path -LiteralPath $customData)) { Write-Host "Папка данных из VERBALIOX_DATA_DIR: $customData$(Size $customData)" }
if ($customModels -and (Test-Path -LiteralPath $customModels) -and -not (Inside $customModels $AppDir)) {
    Write-Host "Папка моделей из VERBALIOX_MODELS_DIR: $customModels$(Size $customModels)"
}
Write-Host ""
Write-Host "Не удаляются: папка записей, выбранная в настройках вне папки данных, файлы, импортированные без"
Write-Host "копирования, экспорт, заметки в Obsidian и архивы резервных копий."
Write-Host ""

if (-not $KeepData -and -not $Yes) {
    Write-Host "Записи, расшифровки и настройки будут удалены без возможности восстановления." -ForegroundColor Yellow
    Write-Host "Чтобы сохранить их, сначала сделайте резервную копию в программе или запустите с -KeepData."
}
if (-not (Ask "Удалить Verbaliox и всё перечисленное?" $true)) {
    Write-Host "Отменено."
    exit 1
}
$removeCustomData = $false
if (-not $KeepData -and $customData -and (Test-Path -LiteralPath $customData)) {
    $removeCustomData = Ask "Удалить и папку данных $customData (её задали переменной VERBALIOX_DATA_DIR)?" $false
}
$removeCustomModels = $false
if ($customModels -and (Test-Path -LiteralPath $customModels) -and -not (Inside $customModels $AppDir)) {
    $removeCustomModels = Ask "Удалить и папку моделей $customModels (её задали переменной VERBALIOX_MODELS_DIR)?" $false
}
$ollamaDir = Join-Path $local "Programs\Ollama"
$removeOllama = $WithOllama -or ((Test-Path -LiteralPath $ollamaDir) -and -not $Yes -and
    (Ask "Удалить и Ollama со всеми её моделями? Её могут использовать другие программы." $false))
$removeUv = $WithUv -or (-not $Yes -and (Get-Command uv.exe -ErrorAction SilentlyContinue) -and
    (Ask "Удалить uv (установщик пакетов Python, ставился при настройке)?" $false))
$python311 = Join-Path $local "Programs\Python\Python311"
$removePython = $WithPython -or ((Test-Path -LiteralPath $python311) -and -not $Yes -and
    (Ask "Удалить Python 3.11 из $python311? Его могут использовать другие программы." $false))

Write-Host ""
Write-Host "1. Закрываю программу" -ForegroundColor Cyan
$me = $PID
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    # not this removal itself (uninstall.bat, the PowerShell it started): only the program's processes
    $_.ProcessId -ne $me -and $_.Name -notin @("powershell.exe", "pwsh.exe", "conhost.exe") -and
    -not ($_.CommandLine -and $_.CommandLine -like "*uninstall*") -and (
        (Inside $_.ExecutablePath $AppDir) -or ($_.CommandLine -and $_.CommandLine -like "*$AppDir*"))
}
foreach ($p in $procs) {
    Write-Host "  завершаю $($p.Name) ($($p.ProcessId))"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
# Ollama keeps its models open: it is stopped when they go (the program's or all of Ollama)
$ollamaModels = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
$ourOllamaModels = $ollamaModels -and ((Inside $ollamaModels $AppDir) -or ($customModels -and (Inside $ollamaModels $customModels)))
if ($removeOllama -or $ourOllamaModels) {
    Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  завершаю $($_.ProcessName) ($($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

Write-Host "2. Автозапуск, запись установщика, ярлыки, переменные" -ForegroundColor Cyan
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
foreach ($name in @("Verbaliox", "VerbaScribe")) {
    if (Get-ItemProperty -Path $run -Name $name -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $run -Name $name -ErrorAction SilentlyContinue
        Write-Host "  убран автозапуск $name"
    }
}
# the name and icon of the app's Windows toasts (app/toast.py)
$toastKey = "HKCU:\Software\Classes\AppUserModelId\Verbaliox.Desktop.Studio.1"
if (Test-Path $toastKey) { Remove-Item -Path $toastKey -Recurse -Force -ErrorAction SilentlyContinue }
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F2C1B8E-4E7A-4C3B-9A51-7D0E2B5C9F14}_is1"
if (Test-Path $uninstallKey) {
    Remove-Item -Path $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  убрана запись в «Установленных приложениях»"
}
$shortcuts = @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Verbaliox.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Verbaliox.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "VerbaScribe.lnk")
)
foreach ($s in $shortcuts) {
    if (Test-Path -LiteralPath $s) { Remove-Item -LiteralPath $s -Force -ErrorAction SilentlyContinue; Write-Host "  убран ярлык $s" }
}
if ($ourOllamaModels -or $removeOllama) {
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $null, "User")
    Write-Host "  убрана переменная OLLAMA_MODELS"
}
if ($removeCustomData) { [Environment]::SetEnvironmentVariable("VERBALIOX_DATA_DIR", $null, "User") }
if ($removeCustomModels) { [Environment]::SetEnvironmentVariable("VERBALIOX_MODELS_DIR", $null, "User") }

Write-Host "3. Временные файлы" -ForegroundColor Cyan
foreach ($pattern in @("verbaliox-*", "vs_backup_*", "vs_restore_*", "vs_pkg_*", "vs_bench_*")) {
    Get-ChildItem -Path $env:TEMP -Filter $pattern -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -ne $PSCommandPath } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}

if (-not $KeepData) {
    Write-Host "4. Данные" -ForegroundColor Cyan
    foreach ($d in $dataDirs) { Remove-Folder $d }
    if ($removeCustomData) { Remove-Folder $customData }
}
if ($removeCustomModels) { Remove-Folder $customModels }

Write-Host "5. Программа" -ForegroundColor Cyan
if ($KeepData) {
    # a data folder inside the program (a Store Python) is kept: everything else goes
    Get-ChildItem -LiteralPath $AppDir -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "data" } |
        ForEach-Object { Remove-Folder $_.FullName; if (Test-Path -LiteralPath $_.FullName) { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue } }
} else {
    Remove-Folder $AppDir
}

if ($removeOllama) {
    Write-Host "6. Ollama" -ForegroundColor Cyan
    $unins = Join-Path $ollamaDir "unins000.exe"
    if (Test-Path -LiteralPath $unins) {
        Start-Process -FilePath $unins -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
    } elseif (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        winget uninstall --id Ollama.Ollama -e --silent --accept-source-agreements | Out-Null
    }
    Remove-Folder $ollamaDir
    Remove-Folder (Join-Path $env:USERPROFILE ".ollama")
    if ($ollamaModels -and (Test-Path -LiteralPath $ollamaModels)) { Remove-Folder $ollamaModels }
}
if ($removeUv) {
    Write-Host "7. uv" -ForegroundColor Cyan
    if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        winget uninstall --id astral-sh.uv -e --silent --accept-source-agreements | Out-Null
    }
    foreach ($f in @("uv.exe", "uvx.exe", "uvw.exe")) {
        $p = Join-Path $env:USERPROFILE ".local\bin\$f"
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
    Remove-Folder (Join-Path $local "uv")
}
if ($removePython) {
    Write-Host "8. Python 3.11" -ForegroundColor Cyan
    if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        winget uninstall --id Python.Python.3.11 -e --silent --accept-source-agreements | Out-Null
    }
}

Write-Host ""
if (Test-Path -LiteralPath $AppDir) {
    Write-Host "Готово, но часть файлов осталась в $AppDir (они заняты). Перезагрузите компьютер и удалите папку вручную." -ForegroundColor Yellow
} else {
    Write-Host "Verbaliox удалён." -ForegroundColor Green
}
if (-not $Yes) { Read-Host "Нажмите Enter, чтобы закрыть окно" | Out-Null }
exit 0
