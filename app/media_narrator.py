"""Optional official ElevenLabs voice; offline macOS voice sample fallback.

This supplies a narrator sample to DramaClaw. It does not replace DramaClaw's
audio generator or assert that a fal/IndexTTS stage is free.
"""
import os
from pathlib import Path
import shutil
import tempfile

from . import automation_control as control, automation_sandbox as sandbox

TEXT = 'Una historia comienza con una idea y cobra vida en cada escena.'


def status():
    from . import voice_pro
    return {'elevenlabs_configured': voice_pro._eleven_configured(),
            'elevenlabs_optional': True, 'paid_calls_blocked': True,
            'offline_fallback_available': bool(shutil.which('say')) and sandbox.available(),
            'fallback': 'macOS installed voice', 'generation_verified': False}


def sample():
    from . import voice_pro
    if control.policy()['kill_switch']:
        raise PermissionError('Automation stopped')
    if os.environ.get('ZAR_MEDIA_VOICE_PROVIDER') == 'elevenlabs' and voice_pro._eleven_configured():
        try:
            control.paid_call('elevenlabs', {'purpose': 'narrator-sample'})
        except PermissionError:
            control.audit('voice', 'PAID_VOICE_BLOCKED', {'provider': 'elevenlabs'})
        else:
            # Explicit provider: never fall through to a paid Gemini request.
            result = voice_pro._eleven_synthesize(TEXT)
            if result:
                return result
    executable = shutil.which('say')
    if not executable or not sandbox.available():
        return None
    root = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'automation' / 'voice'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        output = Path(directory) / 'sample.wav'
        boundary = sandbox.profile([directory, executable], [output], [executable])
        result = sandbox.run([executable, '-o', str(output), '--file-format=WAVE',
                              '--data-format=LEI16@22050', TEXT], directory, boundary, timeout=20)
        if result['exit_code'] or not output.is_file() or output.stat().st_size > 2*1024*1024:
            return None
        audio = output.read_bytes()
        if not audio.startswith(b'RIFF'):
            return None
        control.audit('voice', 'LOCAL_SAMPLE', {'bytes': len(audio)}, {'bytes': len(audio)})
        return audio, 'audio/wav', 'external/macOS-say'
