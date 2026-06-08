param(
  [string]$ProjectDir = (Get-Location).Path,
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$appDir = Join-Path $ProjectDir "hr_resume_ledger"
$app = Join-Path $appDir "app.py"
if (-not (Test-Path $app)) {
  throw "Cannot find hr_resume_ledger\app.py. Use -ProjectDir to point to the project root that contains hr_resume_ledger."
}

$health = "http://127.0.0.1:$Port/api/health"
try {
  $r = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2
  $running = ($r.StatusCode -eq 200)
} catch {
  $running = $false
}

if (-not $running) {
  Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command", "cd '$appDir'; `$env:HR_LEDGER_PORT='$Port'; python app.py"
  )
  Start-Sleep -Seconds 2
}

$url = "http://127.0.0.1:$Port/"
$candidates = @(
  "C:\Program Files\Google\Chrome\Application\chrome.exe",
  "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
  "C:\Chrome\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chrome) {
  Start-Process $chrome $url
} else {
  Start-Process "chrome.exe" $url
}

Write-Host "HR resume ledger opened: $url"
