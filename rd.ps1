$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'recurdyn-config.json') -Raw | ConvertFrom-Json
$taskPython = $config.python_executable
if ([string]::IsNullOrWhiteSpace($taskPython) -or -not (Test-Path -LiteralPath $taskPython)) {
    throw "Python executable is not configured or missing: $taskPython. Run initialize.ps1 or update recurdyn-config.json."
}
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $taskPython -B -m recurdyn_control @args
    $taskExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $taskExitCode
