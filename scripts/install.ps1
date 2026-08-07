# Installs wzed as a user app: shortcut in the Start Menu + automatic startup with Windows.
# Points to the venv's pythonw.exe (signed by the PSF, runs without a console).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1            # install
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall # remove
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -NoAutostart

param(
    [switch]$Uninstall,
    [switch]$NoAutostart
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
# Points to the venv's pythonw.exe (SIGNED by the Python Software Foundation, high
# AV reputation) running `-m wzed`, instead of the generated wzed.exe (unsigned, which
# Norton blocks on reputation). pythonw runs without a console.
$pyw  = Join-Path $repo ".venv\Scripts\pythonw.exe"
$icon = Join-Path $repo "assets\wzed.ico"

$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "wzed.lnk"
$startup   = Join-Path ([Environment]::GetFolderPath("Startup"))  "wzed.lnk"

function Remove-Shortcut($path) {
    if (Test-Path $path) { Remove-Item $path -Force; Write-Host "removed: $path" }
}

if ($Uninstall) {
    Remove-Shortcut $startMenu
    Remove-Shortcut $startup
    Write-Host "wzed uninstalled (the repo and the venv are kept)."
    return
}

if (-not (Test-Path $pyw)) {
    throw "pythonw.exe not found at $pyw. Run 'uv sync' first."
}
if (-not (Test-Path $icon)) {
    Write-Warning "icon not found ($icon); run 'uv run python scripts\make_icon.py'."
    $icon = $pyw
}

function New-Shortcut($path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath       = $pyw
    $sc.Arguments        = "-m wzed"
    $sc.WorkingDirectory = $repo
    $sc.IconLocation     = $icon
    $sc.Description       = "wzed: local voice dictation (hold Ctrl+Win and speak)"
    $sc.WindowStyle      = 7   # minimized; the app lives in the tray anyway
    $sc.Save()
    Write-Host "created: $path -> pythonw.exe -m wzed"
}

New-Shortcut $startMenu
if (-not $NoAutostart) {
    New-Shortcut $startup
    Write-Host "autostart with Windows: ENABLED"
} else {
    Write-Host "autostart: skipped (-NoAutostart)"
}

Write-Host ""
Write-Host "Done. Search for 'wzed' in the Start Menu, or reboot for autostart."
Write-Host "Tray icon: gray = idle, red = recording, blue = transcribing."
Write-Host "Usage: hold Ctrl+Win, speak, release. The text is typed into the focused app."
