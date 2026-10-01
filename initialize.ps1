[CmdletBinding()]
param(
    [string]$PythonExecutable,
    [string]$RecurDynInstallDir,
    [string]$RecurDynHelpIndex,
    [string]$ProcessNetChm,
    [string]$ExamplesRoot,
    [string]$ProcessNetHtmlDir,
    [switch]$ExtractProcessNet,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'

function Get-PythonInfo([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate) -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $null }
    if ($Candidate -match '\\WindowsApps\\') { return $null }
    try {
        $taskProbe = & $Candidate -B -c 'import importlib.util,json,struct,sys; print(json.dumps({"executable":sys.executable,"version":list(sys.version_info[:3]),"bits":struct.calcsize("P")*8,"pywin32":importlib.util.find_spec("win32com") is not None}))' 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $info = ($taskProbe -join "`n") | ConvertFrom-Json
        if ($info.bits -eq 64 -and ($info.version[0] -gt 3 -or ($info.version[0] -eq 3 -and $info.version[1] -ge 10)) -and $info.pywin32) { return $info }
    } catch { return $null }
    return $null
}

$configPath = Join-Path $PSScriptRoot 'recurdyn-config.json'
$existing = $null
if (Test-Path -LiteralPath $configPath) { $existing = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json }

$pythonCandidates = @()
if ($PythonExecutable) {
    $pythonCandidates += $PythonExecutable
} else {
    if ($existing -and $existing.python_executable) { $pythonCandidates += $existing.python_executable }
    if ($env:CONDA_PREFIX) { $pythonCandidates += (Join-Path $env:CONDA_PREFIX 'python.exe') }
    $taskCondaList = Join-Path $env:USERPROFILE '.conda\environments.txt'
    if (Test-Path -LiteralPath $taskCondaList) {
        foreach ($taskEnv in (Get-Content -LiteralPath $taskCondaList)) {
            if (-not [string]::IsNullOrWhiteSpace($taskEnv)) { $pythonCandidates += (Join-Path $taskEnv.Trim() 'python.exe') }
        }
    }
    foreach ($taskCommand in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) { $pythonCandidates += $taskCommand.Source }
}
$validPython = @()
foreach ($candidate in @($pythonCandidates | Select-Object -Unique)) {
    $info = Get-PythonInfo $candidate
    if ($null -ne $info) { $validPython += $info }
}
$validPython = @($validPython | Sort-Object executable -Unique)
if ($validPython.Count -eq 0) {
    throw 'No suitable Python found. Use -PythonExecutable with Windows 64-bit Python 3.10+ containing pywin32. Python 3.10 + RecurDyn 2024 is the tested combination. This script does not install packages.'
}
if ($validPython.Count -gt 1) {
    throw ('Multiple suitable environments found; select one with -PythonExecutable: ' + (($validPython | ForEach-Object { $_.executable }) -join ', '))
}
$pythonInfo = $validPython[0]

$installCandidates = @()
if ($RecurDynInstallDir) {
    $installCandidates += $RecurDynInstallDir
} else {
    if ($existing -and $existing.install_dir) { $installCandidates += $existing.install_dir }
    if ($env:ProgramFiles) { $installCandidates += (Join-Path $env:ProgramFiles 'FunctionBay, Inc\RecurDyn 2024') }
    $installCandidates += 'D:\Program Files\FunctionBay, Inc\RecurDyn 2024'
    foreach ($registryRoot in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
        foreach ($entry in @(Get-ItemProperty -Path ($registryRoot + '\*') -ErrorAction SilentlyContinue)) {
            if ($entry.DisplayName -like '*RecurDyn*2024*' -and $entry.InstallLocation) { $installCandidates += $entry.InstallLocation }
        }
    }
}
$validInstalls = @()
foreach ($candidate in @($installCandidates | Select-Object -Unique)) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $taskInstall = [System.IO.Path]::GetFullPath($candidate).TrimEnd('\')
    if ((Test-Path -LiteralPath (Join-Path $taskInstall 'Bin\RecurDyn.exe') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $taskInstall 'Bin\Python\Lib\recurdyn\ProcessNet.py') -PathType Leaf)) {
        $validInstalls += $taskInstall
    }
}
$validInstalls = @($validInstalls | Select-Object -Unique)
if ($validInstalls.Count -ne 1) {
    throw 'Select a RecurDyn installation containing the official Python SDK with -RecurDynInstallDir. RecurDyn 2024 is the verified version.'
}
$settings = [ordered]@{
    install_dir = $validInstalls[0]
    python_executable = $pythonInfo.executable
    conda_environment = $null
    connect_timeout_seconds = 90
}
function Resolve-DocPath([string]$Provided, [string]$Fallback) {
    $value = if ([string]::IsNullOrWhiteSpace($Provided)) { $Fallback } else { $Provided }
    if (-not [System.IO.Path]::IsPathRooted($value)) { $value = Join-Path $PSScriptRoot $value }
    return [System.IO.Path]::GetFullPath($value)
}
$sameInstallation = $existing -and $existing.install_dir -eq $settings.install_dir
if ($sameInstallation -and $existing.documentation) {
    if (-not $RecurDynHelpIndex) { $RecurDynHelpIndex = $existing.documentation.recurdyn_help_index }
    if (-not $ProcessNetChm) { $ProcessNetChm = $existing.documentation.processnet_chm }
    if (-not $ExamplesRoot) { $ExamplesRoot = $existing.documentation.examples_root }
    if (-not $ProcessNetHtmlDir) { $ProcessNetHtmlDir = $existing.documentation.processnet_html_dir }
}
$settings.documentation = [ordered]@{
    recurdyn_help_index = Resolve-DocPath $RecurDynHelpIndex (Join-Path $settings.install_dir 'Help\RecurDynHelp\index.html')
    processnet_chm = Resolve-DocPath $ProcessNetChm (Join-Path $settings.install_dir 'Help\ProcessNetHelp.chm')
    examples_root = Resolve-DocPath $ExamplesRoot (Join-Path $settings.install_dir 'Help')
    processnet_html_dir = Resolve-DocPath $ProcessNetHtmlDir (Join-Path $PSScriptRoot '.reference\processnet')
}
$documentationCheck = [ordered]@{}
foreach ($key in $settings.documentation.Keys) { $documentationCheck[$key] = Test-Path -LiteralPath $settings.documentation[$key] }
$extraction = $null
if (-not $CheckOnly) {
    $settings | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8
    if ($ExtractProcessNet) {
        Push-Location -LiteralPath $PSScriptRoot
        try {
            $taskExtraction = & $pythonInfo.executable -B -m recurdyn_control docs-extract
            if ($LASTEXITCODE -ne 0) { throw 'CHM extraction failed. Inspect docs-paths and use a new output directory when a pre-existing HTML cache cannot be verified.' }
            $extraction = ($taskExtraction -join "`n") | ConvertFrom-Json
        } finally { Pop-Location }
    }
}
foreach ($key in $settings.documentation.Keys) { $documentationCheck[$key] = Test-Path -LiteralPath $settings.documentation[$key] }
[ordered]@{ ready_for_doctor = $true; config_written = -not [bool]$CheckOnly; config_path = $configPath; settings = $settings; python = $pythonInfo; documentation_exists = $documentationCheck; extraction = $extraction; note = 'Paths and Python dependencies verified. Run rd.ps1 doctor on the Windows host to check COM. License/solver behavior is not verified by initialization.' } | ConvertTo-Json -Depth 6
