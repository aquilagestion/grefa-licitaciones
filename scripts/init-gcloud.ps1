# Anade gcloud al PATH de la sesion actual de PowerShell.
# Uso:  . .\scripts\init-gcloud.ps1

$GcloudRoot = Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk"
$GcloudBin = Join-Path $GcloudRoot "bin"
$GcloudCmd = Join-Path $GcloudBin "gcloud.cmd"

if (-not (Test-Path $GcloudCmd)) {
    Write-Error @"
No se encontro gcloud en:
  $GcloudCmd

Instala Google Cloud SDK:
  winget install Google.CloudSDK
"@
}

if ($env:PATH -notlike "*$GcloudBin*") {
    $env:PATH = "$GcloudBin;$env:PATH"
}

Write-Host "gcloud listo: $GcloudCmd"
Write-Host "Version:"
& $GcloudCmd --version | Select-Object -First 1
