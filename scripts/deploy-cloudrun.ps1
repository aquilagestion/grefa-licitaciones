# Despliegue de GREFA Licitaciones en Google Cloud Run
# Requiere: Google Cloud SDK (gcloud) instalado y permisos en el proyecto.
#
# Uso:
#   .\scripts\deploy-cloudrun.ps1
#   .\scripts\deploy-cloudrun.ps1 -UseServiceAccount   # solo si la SA tiene roles de despliegue

param(
    [switch]$UseServiceAccount
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# gcloud suele instalarse sin anadirse al PATH de Windows.
$InitGcloud = Join-Path $Root "scripts\init-gcloud.ps1"
if (Test-Path $InitGcloud) { . $InitGcloud }

$Project = "licitacionesplacsp-504412"
$Region = "europe-southwest1"
$Service = "grefa-licitaciones"
$SecretName = "grefa-streamlit-secrets"
$SpreadsheetId = "1vR3VeFKuCU1NwnwXcN7fHXJgilpQaI3Jaj0HTSXhNXE"

function Find-Gcloud {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        (Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        "gcloud"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "gcloud") {
            $cmd = Get-Command gcloud -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } elseif (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Invoke-Gcloud {
    param(
        [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $script:Gcloud @Args 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                Write-Host $_.ToString() -ForegroundColor Red
            } else {
                Write-Host $_
            }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-ActiveGcloudAccount {
    $output = & $script:Gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $account = ($output | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($account)) { return $null }
    return $account.Trim()
}

function Show-AuthHelp {
    Write-Host ""
    Write-Host "No hay cuenta de Google Cloud activa en gcloud." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Opcion recomendada: inicia sesion con tu cuenta @grefa.org (Editor o Owner del proyecto):"
    Write-Host "  gcloud auth login"
    Write-Host "  gcloud config set project $Project"
    Write-Host "  .\scripts\deploy-cloudrun.ps1"
    Write-Host ""
    Write-Host "Opcion alternativa (solo si la cuenta de servicio tiene roles Cloud Run + Cloud Build):"
    Write-Host "  .\scripts\deploy-cloudrun.ps1 -UseServiceAccount"
    Write-Host ""
}

$Gcloud = Find-Gcloud
if (-not $Gcloud) {
    Write-Error "No se encontro gcloud. Instala Google Cloud SDK: winget install Google.CloudSDK"
}

if ($UseServiceAccount) {
    $SaKey = Join-Path $Root "service-account.json"
    if (-not (Test-Path $SaKey)) {
        Write-Error "No existe $SaKey"
    }
    Write-Host ">> Autenticando con cuenta de servicio..."
    $code = Invoke-Gcloud auth activate-service-account --key-file=$SaKey
    if ($code -ne 0) { exit $code }
} else {
    $active = Get-ActiveGcloudAccount
    if (-not $active) {
        Show-AuthHelp
        exit 1
    }
    Write-Host ">> Cuenta activa: $active"
}

Write-Host ">> Proyecto: $Project | Region: $Region | Servicio: $Service"
$code = Invoke-Gcloud config set project $Project
if ($code -ne 0) { exit $code }

Write-Host ">> Habilitando APIs necesarias..."
$code = Invoke-Gcloud services enable run.googleapis.com cloudbuild.googleapis.com sheets.googleapis.com drive.googleapis.com secretmanager.googleapis.com --quiet
if ($code -ne 0) {
    Write-Host ""
    Write-Host "No se pudieron habilitar las APIs. Comprueba permisos del proyecto." -ForegroundColor Red
    exit $code
}

$SecretsFile = Join-Path $Root ".streamlit\secrets.toml"
if (-not (Test-Path $SecretsFile)) {
    Write-Error "Falta $SecretsFile - copia secrets.toml.example y rellenalo."
}

Write-Host ">> Actualizando secreto en Secret Manager..."
$code = Invoke-Gcloud secrets describe $SecretName
if ($code -ne 0) {
    $code = Invoke-Gcloud secrets create $SecretName --data-file=$SecretsFile
} else {
    $code = Invoke-Gcloud secrets versions add $SecretName --data-file=$SecretsFile
}
if ($code -ne 0) { exit $code }

$SecretsMount = "/home/grefa/.streamlit/secrets.toml=${SecretName}:latest"
$EnvVars = "GREFA_SPREADSHEET_ID=$SpreadsheetId"

Write-Host ">> Desplegando en Cloud Run (build remoto, ~5-10 min)..."
$code = Invoke-Gcloud run deploy $Service `
    --source . `
    --region $Region `
    --allow-unauthenticated `
    --port 8080 `
    --cpu 1 `
    --memory 1Gi `
    --timeout 3600 `
    --session-affinity `
    --min-instances 0 `
    --max-instances 3 `
    --set-env-vars $EnvVars `
    --set-secrets $SecretsMount
if ($code -ne 0) { exit $code }

Write-Host ""
Write-Host "Despliegue completado. URL del servicio:"
Invoke-Gcloud run services describe $Service --region $Region --format 'value(status.url)'
