# Despliegue en Streamlit Community Cloud
# Repo: https://github.com/aquilagestion/grefa-licitaciones

param(
    [string]$StreamlitToken = $env:STREAMLIT_API_TOKEN,
    [string]$Repo = "aquilagestion/grefa-licitaciones",
    [string]$Branch = "main",
    [string]$MainFile = "app.py",
    [string]$AppName = "grefa-licitaciones"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Open-DeployPage {
    $url = "https://share.streamlit.io/deploy?repository=$Repo&branch=$Branch&mainModule=$MainFile"
    Write-Host ">> Abriendo despliegue en navegador:"
    Write-Host "   $url"
    Start-Process $url
}

function Push-SecretsViaApi {
    param([string]$Token, [string]$AppId)
    $secretsFile = Join-Path $Root ".streamlit\secrets.toml"
    if (-not (Test-Path $secretsFile)) {
        Write-Error "No existe $secretsFile"
    }
    $body = Get-Content $secretsFile -Raw -Encoding UTF8
    $headers = @{
        Authorization = "Bearer $Token"
        "Content-Type" = "text/plain"
    }
    Invoke-RestMethod -Method Put -Uri "https://api.streamlit.io/v1/apps/$AppId/secrets" -Headers $headers -Body $body
}

Write-Host ">> Comprobando push en GitHub..."
git fetch origin 2>$null
$local = git rev-parse HEAD
$remote = git rev-parse origin/main 2>$null
if ($LASTEXITCODE -ne 0 -or $local -ne $remote) {
    Write-Host ">> Subiendo codigo..."
    git push -u origin main
}

if ($StreamlitToken) {
    Write-Host ">> Desplegando via API de Streamlit Cloud..."
    $headers = @{
        Authorization = "Bearer $StreamlitToken"
        "Content-Type" = "application/json"
    }
    $payload = @{
        repo = $Repo
        branch = $Branch
        mainFile = $MainFile
        appName = $AppName
    } | ConvertTo-Json

    try {
        $app = Invoke-RestMethod -Method Post -Uri "https://api.streamlit.io/v1/apps" -Headers $headers -Body $payload
        Write-Host ">> App desplegada: $($app.url)"
        if ($app.id) {
            Push-SecretsViaApi -Token $StreamlitToken -AppId $app.id
            Write-Host ">> Secrets actualizados."
        }
        exit 0
    } catch {
        Write-Host "API fallo: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "Continuando con despliegue manual en navegador..."
    }
}

Write-Host ""
Write-Host "PASO UNICO que requiere tu clic (solo la primera vez):"
Write-Host "  1. Inicia sesion en Streamlit con GitHub (cuenta aquilagestion)."
Write-Host "  2. Autoriza acceso al repo privado grefa-licitaciones."
Write-Host "  3. Pulsa Deploy."
Write-Host ""
Write-Host "Despues, en Settings -> Secrets, pega el contenido de:"
Write-Host "  $Root\.streamlit\secrets.toml"
Write-Host ""

$secretsPath = Join-Path $Root ".streamlit\secrets.toml"
if (Test-Path $secretsPath) {
    try {
        Get-Content $secretsPath -Raw -Encoding UTF8 | Set-Clipboard
        Write-Host ">> Secrets copiados al portapapeles. Pegalos en Streamlit Cloud -> Settings -> Secrets." -ForegroundColor Green
    } catch {
        Write-Host ">> Copia manualmente secrets.toml al panel de Streamlit." -ForegroundColor Yellow
    }
}

Open-DeployPage
