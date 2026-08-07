# Instala o wzed como app do usuário: atalho no Menu Iniciar + início automático com o Windows.
# Aponta para o wzed.exe (gui-script, roda sem console) gerado por `uv sync`.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1            # instala
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall # remove
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -NoAutostart

param(
    [switch]$Uninstall,
    [switch]$NoAutostart
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
# Aponta para o pythonw.exe do venv (ASSINADO pela Python Software Foundation, alta
# reputação de AV) rodando `-m wzed`, em vez do wzed.exe gerado (não assinado, que o
# Norton bloqueia por reputação). O pythonw roda sem console.
$pyw  = Join-Path $repo ".venv\Scripts\pythonw.exe"
$icon = Join-Path $repo "assets\wzed.ico"

$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "wzed.lnk"
$startup   = Join-Path ([Environment]::GetFolderPath("Startup"))  "wzed.lnk"

function Remove-Shortcut($path) {
    if (Test-Path $path) { Remove-Item $path -Force; Write-Host "removido: $path" }
}

if ($Uninstall) {
    Remove-Shortcut $startMenu
    Remove-Shortcut $startup
    Write-Host "wzed desinstalado (o repo e o venv permanecem)."
    return
}

if (-not (Test-Path $pyw)) {
    throw "pythonw.exe não encontrado em $pyw. Rode 'uv sync' primeiro."
}
if (-not (Test-Path $icon)) {
    Write-Warning "ícone não encontrado ($icon); rode 'uv run python scripts\make_icon.py'."
    $icon = $pyw
}

function New-Shortcut($path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath       = $pyw
    $sc.Arguments        = "-m wzed"
    $sc.WorkingDirectory = $repo
    $sc.IconLocation     = $icon
    $sc.Description       = "wzed: ditado por voz local (segure Ctrl+Win e fale)"
    $sc.WindowStyle      = 7   # minimizado; o app vive na bandeja de qualquer forma
    $sc.Save()
    Write-Host "criado: $path -> pythonw.exe -m wzed"
}

New-Shortcut $startMenu
if (-not $NoAutostart) {
    New-Shortcut $startup
    Write-Host "início automático com o Windows: ATIVADO"
} else {
    Write-Host "início automático: pulado (-NoAutostart)"
}

Write-Host ""
Write-Host "Pronto. Procure 'wzed' no menu Iniciar, ou reinicie para o autostart."
Write-Host "Ícone da bandeja: cinza=ocioso, vermelho=gravando, azul=processando."
Write-Host "Uso: segure Ctrl+Win, fale, solte. O texto é digitado no app em foco."
