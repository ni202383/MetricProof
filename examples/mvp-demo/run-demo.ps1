$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

& metricproof experiments validate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& metricproof scan --show-claims
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& metricproof link --non-interactive --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& metricproof check
$checkStatus = $LASTEXITCODE
if ($checkStatus -ne 1) {
    Write-Error "Expected metricproof check to exit 1; got $checkStatus"
    if ($checkStatus -eq 0) { exit 2 }
    exit $checkStatus
}

& metricproof report --format html --output metricproof-report.html --no-timestamp
$reportStatus = $LASTEXITCODE
if ($reportStatus -ne 1) {
    Write-Error "Expected metricproof report to exit 1; got $reportStatus"
    if ($reportStatus -eq 0) { exit 2 }
    exit $reportStatus
}

Write-Host "Created $PSScriptRoot\metricproof-report.html"
Write-Host "Demo findings intentionally meet the configured threshold."
exit 1
