Write-Host "=== Zar: comprobación de Ollama ===" -ForegroundColor Cyan
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Ollama no está instalado." -ForegroundColor Yellow
    Write-Host "Instálalo desde https://ollama.com/download/windows y vuelve a ejecutar este script."
    exit 1
}
Write-Host "Ollama encontrado."
Write-Host "Descargando Qwen3 8B..."
ollama pull qwen3:8b
if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo descargar qwen3:8b." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Prueba rápida..."
ollama run qwen3:8b "Responde exactamente: ZAR LOCAL FUNCIONANDO" --keepalive 5m
