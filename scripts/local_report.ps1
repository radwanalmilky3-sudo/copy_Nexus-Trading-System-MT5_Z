# local_report.ps1 — نبض Nexus المحلي: يدفع لقطة صحية (بلا أسرار) إلى المستودع
# ليقرأها المطور السحابي (ZAI) في دورة القناة. التشغيل اليدوي:
#   powershell -ExecutionPolicy Bypass -File scripts\local_report.ps1
# المتوقع: REPORT_PUSHED (أو REPORT_NOCHANGE_PUSHED إن لم يتغير شيء)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$services = [ordered]@{}
foreach ($p in 9000..9008) {
  $code = & curl.exe -s -o NUL -w "%{http_code}" --max-time 5 "http://127.0.0.1:$p/health"
  if ([string]::IsNullOrEmpty($code)) { $code = "000" }
  $services["$p"] = $code
}
$dash = & curl.exe -s -o NUL -w "%{http_code}" --max-time 5 "http://127.0.0.1:3100/"
if ([string]::IsNullOrEmpty($dash)) { $dash = "000" }

$report = [ordered]@{
  generated_at   = (Get-Date -Format o)
  host           = $env:COMPUTERNAME
  services       = $services
  dashboard_3100 = $dash
  note           = "health codes only - no secrets, no trades, no keys"
}

$dir = Join-Path $root "local_reports"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Set-Content -Path (Join-Path $dir "latest.json") -Value ($report | ConvertTo-Json -Depth 3) -Encoding UTF8

& git add local_reports/latest.json
& git commit -m "local: health pulse" 2>&1 | Out-Null
$committed = ($LASTEXITCODE -eq 0)
& git pull --rebase origin main 2>&1 | Out-Null
& git push origin main 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  if ($committed) { Write-Host "REPORT_PUSHED" } else { Write-Host "REPORT_NOCHANGE_PUSHED" }
} else {
  Write-Host "PUSH_FAILED - الصق هذا المخرج للمطور السحابي"
}
