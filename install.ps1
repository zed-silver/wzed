<#
  wzed — one-click installer.

  Sets up wzed from a fresh clone: installs the uv package manager (if missing),
  creates the virtual environment, builds the tray icon, and adds the Start Menu
  and autostart shortcuts. Safe to run again at any time to update an install.

  Run it by double-clicking install.bat, or from a terminal:

      powershell -ExecutionPolicy Bypass -File install.ps1

  Flags:
      -NoAutostart   do not start wzed automatically with Windows
      -NoStart       do not launch wzed at the end of the install
      -Uninstall     remove the shortcuts (the repo and the venv are kept)
#>
param(
    [switch]$Uninstall,
    [switch]$NoAutostart,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

function Say($msg, $color = "Gray")  { Write-Host $msg -ForegroundColor $color }
function Step($n, $msg)              { Write-Host "`n[$n] $msg" -ForegroundColor White }

Write-Host ""
Say "  wzed - 100% local voice dictation for Windows" "Cyan"
Say "  installer" "DarkGray"

# --- Uninstall path --------------------------------------------------------
if ($Uninstall) {
    & (Join-Path $repo "scripts\install.ps1") -Uninstall
    return
}

# --- 1. Ensure uv (the Python package manager) -----------------------------
Step 1 "Checking for uv..."
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Say "    uv not found - trying to install it with winget..." "Yellow"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
        # Refresh PATH for this session so the freshly installed uv is visible,
        # and add uv's default install dir as a fallback.
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    (Join-Path $env:USERPROFILE ".local\bin")
        $uv = Get-Command uv -ErrorAction SilentlyContinue
    }
}
if (-not $uv) {
    Say "    Could not install uv automatically." "Red"
    Say "    Install it once, reopen the terminal, and run this again:" "Red"
    Say '      winget install astral-sh.uv' "White"
    Say '      (or)  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"' "White"
    throw "uv is required and was not found on PATH."
}
$uvVersion = (& uv --version) 2>&1
Say "    uv OK ($uvVersion)" "Green"

# --- 2. Create the virtual environment -------------------------------------
Step 2 "Installing dependencies into .venv..."
Say "    First run downloads the STT models' backend (CUDA/PyTorch) - can take a few minutes." "DarkGray"
# `dev` is a dependency-group (installed by uv sync by default); only `api` is an extra.
& uv sync --extra api
if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)." }
Say "    environment ready." "Green"

# --- 3. Build the tray icon ------------------------------------------------
Step 3 "Generating the tray icon..."
& uv run python scripts\make_icon.py
if ($LASTEXITCODE -ne 0) {
    Say "    icon generation failed (non-fatal) - a default icon will be used." "Yellow"
} else {
    Say "    icon ready." "Green"
}

# --- 4. Start Menu + autostart shortcuts -----------------------------------
Step 4 "Creating Start Menu and autostart shortcuts..."
$forward = @()
if ($NoAutostart) { $forward += "-NoAutostart" }
& (Join-Path $repo "scripts\install.ps1") @forward

# --- 5. Launch -------------------------------------------------------------
if (-not $NoStart) {
    Step 5 "Starting wzed..."
    $pyw = Join-Path $repo ".venv\Scripts\pythonw.exe"
    Start-Process $pyw -ArgumentList "-m", "wzed" -WorkingDirectory $repo
    Say "    wzed is running - the icon is in the notification-area overflow (the ^ arrow)." "Green"
    Say "    First boot loads the model and can take ~15 s before the hotkey responds." "DarkGray"
}

Write-Host ""
Say "Done. Hold Ctrl+Win, speak, release - your words are typed into the focused app." "Cyan"
Say "Tray icon:  gray = idle   red = recording   blue = transcribing" "DarkGray"
Say "To remove:  .\install.ps1 -Uninstall   (or double-click uninstall.bat)" "DarkGray"
