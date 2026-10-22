$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path ".env")) {
    throw "Missing .env. Create it from .env.example before deployment."
}

docker compose pull
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

docker compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$portMapping = (docker compose port web 8000 | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $portMapping -notmatch '^(?<host>\[[^\]]+\]|[^:]+):(?<port>\d+)$') {
    throw "Unable to determine the published web address from Docker Compose."
}

$healthHost = $Matches.host.Trim("[", "]")
$healthPort = $Matches.port
if ($healthHost -in @("0.0.0.0", "::")) {
    $healthHost = "127.0.0.1"
}

$healthUrl = "http://${healthHost}:${healthPort}/health"
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        $response | ConvertTo-Json -Depth 5
        exit 0
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

throw "Deployment finished, but $healthUrl did not become healthy in 30 seconds."
