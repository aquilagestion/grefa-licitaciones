# Prepara y publica en Streamlit Community Cloud (gratis, sin billing GCP).
#
# Uso:
#   .\scripts\preparar-streamlit-cloud.ps1
#   .\scripts\preparar-streamlit-cloud.ps1 -CommitMessage "Monitor GREFA PLACSP"

param(
    [string]$CommitMessage = "Monitor GREFA licitaciones PLACSP"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host ">> Comprobando estructura..."
foreach ($file in @("app.py", "requirements.txt", ".streamlit/config.toml", "data/cpv_es.csv")) {
    if (-not (Test-Path (Join-Path $Root $file))) {
        Write-Error "Falta $file"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git no esta instalado."
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Host ">> Inicializando repositorio git..."
    git init
    git branch -M main
}

Write-Host ">> Comprobando que no se suban secretos..."
$trackedSecrets = git ls-files -- ".streamlit/secrets.toml" "service-account.json" 2>$null
if ($trackedSecrets) {
    Write-Error "Hay secretos en el indice git. Ejecuta: git rm --cached .streamlit/secrets.toml service-account.json"
}

git add -A
$status = git status --porcelain
if (-not $status) {
    Write-Host ">> Sin cambios nuevos que commitear."
} else {
    Write-Host ">> Creando commit..."
    git commit -m $CommitMessage
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  PASOS EN GITHUB + STREAMLIT CLOUD" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "1. Crea un repo PRIVADO en GitHub:"
Write-Host "   https://github.com/new"
Write-Host "   Nombre sugerido: grefa-licitaciones"
Write-Host "   NO marques README ni .gitignore (ya existen aqui)."
Write-Host ""
Write-Host "2. Enlaza y sube (cambia TU_USUARIO):"
Write-Host "   git remote add origin https://github.com/TU_USUARIO/grefa-licitaciones.git"
Write-Host "   git push -u origin main"
Write-Host ""
Write-Host "3. Despliega en Streamlit Cloud:"
Write-Host "   https://share.streamlit.io"
Write-Host "   - Create app -> elige el repo"
Write-Host "   - Main file path: app.py"
Write-Host "   - Branch: main"
Write-Host ""
Write-Host "4. Secrets (Settings -> Secrets): pega el contenido de:"
Write-Host "   .streamlit\secrets.toml"
Write-Host "   (incluye [sheets] y [gcp_service_account]; NO subas ese fichero a GitHub)"
Write-Host ""
Write-Host "5. Si activas login [auth], en Google OAuth anade la URI:"
Write-Host "   https://TU-APP.streamlit.app/oauth2callback"
Write-Host ""
Write-Host "6. Advanced settings (opcional): Python 3.12"
Write-Host ""
Write-Host "URL final: https://TU-APP.streamlit.app"
