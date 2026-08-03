# Arranca Streamlit + tunel publico (sin billing, sin login en Streamlit Cloud).
# Ejecutar una vez y dejar la ventana abierta (o usar iniciar-servicio.ps1).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Puerto = 8502

function Find-Cloudflared {
    $candidates = @(
        (Join-Path $env:ProgramFiles "cloudflared\cloudflared.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "cloudflared\cloudflared.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Set-Location $Root

# Streamlit
$streamlitUp = $false
try {
    $h = Invoke-WebRequest -Uri "http://localhost:$Puerto/_stcore/health" -UseBasicParsing -TimeoutSec 2
    $streamlitUp = ($h.StatusCode -eq 200)
} catch { $streamlitUp = $false }

if (-not $streamlitUp) {
    Write-Host ">> Arrancando Streamlit en puerto $Puerto..."
    Start-Process -FilePath "python" -ArgumentList "-m streamlit run app.py --server.port $Puerto --server.headless true" -WorkingDirectory $Root -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

$cf = Find-Cloudflared
if (-not $cf) {
    Write-Error "Instala cloudflared: winget install Cloudflare.cloudflared"
}

Write-Host ">> Tunel publico hacia http://localhost:$Puerto"
Write-Host ">> Busca la URL https://....trycloudflare.com en la salida."
& $cf tunnel --url "http://localhost:$Puerto"
