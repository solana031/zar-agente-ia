param([switch]$Login, [switch]$Once)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot '.local/instagram-runtime/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Instala requirements-instagram-worker.txt en .local/instagram-runtime con Python 3.12.'
}
Push-Location $taskRoot
try {
    $taskArguments = @('scripts/zar-local-worker.py')
    if ($Login) { $taskArguments += '--login' }
    if ($Once) { $taskArguments += '--once' }
    & $taskPython @taskArguments
} finally { Pop-Location }
