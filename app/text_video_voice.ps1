param([string]$TextFile,[string]$OutputFile,[string]$Language='es-ES')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $speech.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $Language.Substring(0,2) } | Select-Object -First 1
    if (-not $voice) { throw 'LOCAL_LANGUAGE_VOICE_UNAVAILABLE' }
    $speech.SelectVoice($voice.VoiceInfo.Name)
    $speech.SetOutputToWaveFile($OutputFile)
    $speech.Speak([System.IO.File]::ReadAllText($TextFile,[System.Text.Encoding]::UTF8))
    @{provider='WINDOWS_INSTALLED_TTS';voice=$voice.VoiceInfo.Name;language=$voice.VoiceInfo.Culture.Name} | ConvertTo-Json -Compress
} finally { $speech.Dispose() }
