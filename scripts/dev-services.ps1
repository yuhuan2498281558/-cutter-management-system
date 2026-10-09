#requires -Version 7.0
param(
    [ValidateSet('start', 'status', 'stop')]
    [string]$Action = 'start',
    [string]$Python = 'python',
    [string]$Node = 'node'
)
$ErrorActionPreference = 'Stop'
$pythonExecutable = (Get-Command $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$nodeExecutable = (Get-Command $Node -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
& $pythonExecutable (Join-Path $PSScriptRoot 'dev_services.py') $Action --python $pythonExecutable --node $nodeExecutable
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
