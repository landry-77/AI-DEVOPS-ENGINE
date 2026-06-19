param(
    [Parameter(Position=0)]
    [ValidateSet("setup","sandbox","up","down","logs","status","demo","clean")]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host @"

AI DevOps Engine — PowerShell Quickstart

Commands:
  .\setup.ps1 setup     One-command quickstart (secrets + .env + certs)
  .\setup.ps1 sandbox   Pre-bake sandbox Docker images
  .\setup.ps1 up        Launch local dev stack (docker-compose.local.yml)
  .\setup.ps1 down      Stop all containers
  .\setup.ps1 logs      Tail logs from all services
  .\setup.ps1 status    Show container health
  .\setup.ps1 demo      Send a test PR webhook via curl
  .\setup.ps1 clean     Stop + remove volumes + prune sandboxes

"@
}

function Invoke-Setup {
    Write-Host "==> AI DevOps Engine Setup" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "  [1/5] .env created from .env.example" -ForegroundColor Green
    } else {
        Write-Host "  [1/5] .env already exists — skipping" -ForegroundColor Yellow
    }

    Write-Host "  [2/5] Generating DJANGO_SECRET_KEY..." -ForegroundColor Cyan
    $djangoKey = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 50 | ForEach-Object { [char]$_ })
    (Get-Content .env) -replace '^DJANGO_SECRET_KEY=.*', "DJANGO_SECRET_KEY=$djangoKey" | Set-Content .env

    Write-Host "  [3/5] Generating FERNET_KEY..." -ForegroundColor Cyan
    try {
        $fernetScript = 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
        $fernetKey = python -c $fernetScript
        (Get-Content .env) -replace '^FERNET_KEY=.*', "FERNET_KEY=$fernetKey" | Set-Content .env
        Write-Host "    FERNET_KEY generated" -ForegroundColor Green
    } catch {
        Write-Host "    [WARN] cryptography not installed — run: pip install cryptography" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "  [4/5] OpenRouter API key" -ForegroundColor Cyan
    Write-Host "    Get one free at: https://openrouter.ai/keys" -ForegroundColor Gray
    $orKey = Read-Host "    Paste your sk-or-v1-... key"
    (Get-Content .env) -replace '^OPENROUTER_API_KEY=.*', "OPENROUTER_API_KEY=$orKey" | Set-Content .env

    Write-Host "  [5/5] Creating certs/ directory..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path "certs" -Force | Out-Null

    Write-Host ""
    Write-Host "==> Setup complete!" -ForegroundColor Green
    Write-Host "    Next steps:" -ForegroundColor Cyan
    Write-Host "      1. Place your GitHub App .pem in certs/github_app.pem"
    Write-Host "      2. Edit .env: set GITHUB_APP_IDENTIFIER and GITHUB_WEBHOOK_SECRET"
    Write-Host "      3. Run: .\setup.ps1 sandbox"
    Write-Host "      4. Run: .\setup.ps1 up"
}

function Invoke-Sandbox {
    Write-Host "==> Pre-baking sandbox Docker images..." -ForegroundColor Cyan
    docker build -t local-pytest-sandbox -f sandbox-env/Dockerfile.python sandbox-env/
    if ($?) { docker build -t local-jest-sandbox -f sandbox-env/Dockerfile.javascript sandbox-env/ }
    if ($?) { Write-Host "==> Sandbox images ready" -ForegroundColor Green }
}

function Invoke-Up {
    Write-Host "==> Launching local dev stack..." -ForegroundColor Cyan
    docker compose -f docker-compose.local.yml up --build -d
    if ($?) {
        Write-Host ""
        Write-Host "    Dashboard: http://localhost:8000" -ForegroundColor Green
        Write-Host "    Gateway:   http://localhost:3000" -ForegroundColor Green
        Write-Host ""
        Write-Host "    To expose via ngrok: .\setup.ps1 tunnel" -ForegroundColor Cyan
    }
}

function Invoke-Down {
    docker compose -f docker-compose.yml down 2>$null
    docker compose -f docker-compose.local.yml down 2>$null
    Write-Host "==> Stack stopped" -ForegroundColor Yellow
}

function Invoke-Logs {
    docker compose logs -f
}

function Invoke-Status {
    Write-Host "==> Container Health" -ForegroundColor Cyan
    docker ps --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}" | Select-String "(edge|core|async|scheduled|enterprise|control|production|local)"
}

function Invoke-Tunnel {
    Write-Host "==> In a new terminal, run:" -ForegroundColor Cyan
    Write-Host "    ngrok http http://localhost:3000" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Then set GitHub App Webhook URL to:" -ForegroundColor Cyan
    Write-Host "    https://<your-id>.ngrok-free.app/webhooks/github" -ForegroundColor Yellow
}

function Invoke-Demo {
    $secret = Read-Host "Webhook secret (from .env)"
    $payload = '{"action":"opened","pull_request":{"number":1},"repository":{"id":101,"full_name":"local-org/test-repo","clone_url":"local_vfs"},"installation":{"id":202}}'
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    $hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
    $hash = $hmac.ComputeHash($bytes)
    $sig = ($hash | ForEach-Object { $_.ToString("x2") }) -join ""
    curl.exe -s -X POST http://localhost:3000/webhooks/github `
        -H "Content-Type: application/json" `
        -H "x-github-event: pull_request" `
        -H "x-hub-signature-256: sha256=$sig" `
        -d $payload
}

function Invoke-Clean {
    Write-Host "==> Stopping and removing all containers..." -ForegroundColor Red
    docker compose -f docker-compose.yml down -v 2>$null
    docker compose -f docker-compose.local.yml down -v 2>$null
    Write-Host "==> Pruning orphaned sandbox containers..." -ForegroundColor Red
    docker ps -a --filter "name=sandbox" --format "{{.ID}}" | ForEach-Object { docker rm -f $_ 2>$null }
    Write-Host "==> Clean complete" -ForegroundColor Green
}

switch ($Command) {
    "setup"   { Invoke-Setup }
    "sandbox" { Invoke-Sandbox }
    "up"      { Invoke-Up }
    "down"    { Invoke-Down }
    "logs"    { Invoke-Logs }
    "status"  { Invoke-Status }
    "demo"    { Invoke-Demo }
    "clean"   { Invoke-Clean }
    default   { Show-Help }
}
