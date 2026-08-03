# Expone la app Streamlit local en una URL publica temporal (gratis, sin facturacion GCP).
# Requiere: Streamlit corriendo en el puerto indicado (por defecto 8502).
#
# Uso:
#   Terminal 1:  python -m streamlit run app.py --server.port 8502
#   Terminal 2:  .\scripts\exponer-tunel.ps1
#
# Obtendras una URL tipo https://xxxx.trycloudflare.com
# Nota: la URL cambia cada vez que reinicias el tunel (plan gratuito).

param(
    [int]$Puerto = 8502
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Find-Cloudflared {
    $candidates = @(
        (Join-Path $env:ProgramFiles "cloudflared\cloudflared.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "cloudflared\cloudflared.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "cloudflared") {
            $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } elseif (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

try {
    $health = Invoke-WebRequest -Uri "http://localhost:$Puerto/_stcore/health" -UseBasicParsing -TimeoutSec 3
    if ($health.StatusCode -ne 200) { throw "Streamlit no responde" }
} catch {
    Write-Host ""
    Write-Host "Streamlit no esta activo en http://localhost:$Puerto" -ForegroundColor Yellow
    Write-Host "Arrancalo primero en otra terminal:"
    Write-Host "  cd $Root"
    Write-Host "  python -m streamlit run app.py --server.port $Puerto"
    Write-Host ""
    exit 1
}

$Cloudflared = Find-Cloudflared
if (-not $Cloudflared) {
    Write-Host ""
    Write-Host "cloudflared no esta instalado." -ForegroundColor Yellow
    Write-Host "Instalalo con:"
    Write-Host "  winget install Cloudflare.cloudflared"
    Write-Host ""
    Write-Host "Luego vuelve a ejecutar este script."
    exit 1
}

Write-Host ""
Write-Host ">> Tunel Cloudflare hacia http://localhost:$Puerto"
Write-Host ">> Comparte la URL https://....trycloudflare.com que aparezca abajo."
Write-Host ">> Pulsa Ctrl+C para cerrar el tunel."
Write-Host ""

& $Cloudflared tunnel --url "http://localhost:$Puerto"
