# Restaura la constitucion ORIGINAL de Conway Automaton (Conway-Research/automaton)
# en este PC, eliminando las normas personalizadas. Guarda copia de seguridad antes.
# No toca claves, wallet, estado ni el modo Paper/Risk de ZAR Stonks.
$ErrorActionPreference = 'Stop'
$url = 'https://raw.githubusercontent.com/Conway-Research/automaton/main/constitution.md'
$home_dir = Join-Path $HOME '.automaton'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $home_dir "backup-normas-$stamp"
$original = (Invoke-WebRequest -UseBasicParsing $url).Content
if ($original -notmatch '## I\. Never harm\.' -or $original -notmatch '## III\. Never deceive') { throw 'Descarga inesperada: no se ha modificado nada.' }

$targets = @((Join-Path $home_dir 'constitution.md'))
$upstream = Join-Path (Split-Path $PSScriptRoot -Parent) '.local\upstream\automaton\constitution.md'
if (Test-Path $upstream) { $targets += $upstream }

New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($file in $targets) {
  if (Test-Path $file) {
    Copy-Item $file (Join-Path $backup ((Split-Path $file -Leaf) + '.' + [IO.Path]::GetFileName((Split-Path $file -Parent)))) -Force
    Set-ItemProperty $file -Name IsReadOnly -Value $false
  } elseif (-not (Test-Path (Split-Path $file -Parent))) { continue }
  [IO.File]::WriteAllText($file, $original, (New-Object Text.UTF8Encoding $false))
  Set-ItemProperty $file -Name IsReadOnly -Value $true   # upstream instala la constitucion como solo lectura
  Write-Host "Constitucion original restaurada: $file"
}
Write-Host "Copia de seguridad de tus normas anteriores: $backup"
Write-Host 'Si anadiste normas en el genesis prompt o en SOUL.md, revisalos en' $home_dir '(el genesis es propio de cada instalacion; no existe version original).'
