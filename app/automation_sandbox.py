"""macOS Seatbelt boundary for real installed CLIs, fail closed elsewhere.

No host home, credentials, repository metadata or external network is granted.
Model shell tools are disabled separately: a prompt is not a sandbox boundary.
"""
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time


def available():
    return bool(shutil.which('sandbox-exec'))


def profile(read_paths, write_paths=(), executables=(), local_model=False, temporary_delete_paths=()):
    quote = lambda p: json.dumps(str(Path(p).resolve()))
    lines = ['(version 1)', '(deny default)', '(allow process-fork)',
             '(allow sysctl-read)', '(allow signal (target self))',
             '(allow file-read-metadata)', '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))']
    for p in ['/System', '/usr/lib', '/usr/share', '/Library/Apple', '/private/var/db/dyld', *read_paths]:
        lines.append(f'(allow file-read* (subpath {quote(p)}))')
    for p in write_paths:
        lines.append(f'(allow file-write* (literal {quote(p)}))')
    for p in executables:
        lines.append(f'(allow process-exec (literal {quote(p)}))')
    # getcwd()/the loader need directory traversal, not files in those dirs.
    directories = {parent for p in [*read_paths, *write_paths, *executables]
                   for parent in Path(p).resolve().parents}
    for directory in sorted(directories):
        lines.append(f'(allow file-read* (literal {quote(directory)}))')
    if local_model:
        # Ventura Seatbelt accepts localhost or *, not numeric IP hosts here.
        # localhost denotes loopback (IPv4/IPv6); the port remains exact.
        lines.append('(allow network-outbound (remote ip "localhost:11434"))')
    deny_delete = '(deny file-write-unlink)'
    if temporary_delete_paths:
        exceptions = ' '.join(f'(require-not (literal {quote(p)}))' for p in temporary_delete_paths)
        deny_delete = f'(deny file-write-unlink (require-all {exceptions}))'
    lines += ['(deny file-read* (regex #"/\\.env([^/]*|/.*)$") (regex #"/(\\.ssh|\\.aws|\\.git|\\.codex)(/|$)"))',
              deny_delete, '(deny file-write* (regex #"/\\.git(/|$)"))']
    return '\n'.join(lines)


def run(argv, cwd, sandbox_profile, timeout=30, stdin='', cancelled=lambda:False):
    if not available():
        raise PermissionError('OS sandbox unavailable; execution refused')
    if not 0 < timeout <= 300:
        raise ValueError('Invalid timeout')
    if any(not isinstance(x,str) for x in argv):
        raise ValueError('Invalid invocation')
    # Only the working directory entry, never its children, is added here.
    sandbox_profile += '\n(allow file-read* (literal '+json.dumps(str(Path(cwd).resolve()))+'))'
    env = {'PATH':'/usr/bin:/bin', 'HOME':str(cwd), 'TMPDIR':str(cwd),
           'CODEX_HOME':str(Path(cwd)/'codex-home'), 'PYTHONDONTWRITEBYTECODE':'1',
           'CODEX_OSS_BASE_URL':'http://127.0.0.1:11434/v1', 'LANG':'en_US.UTF-8'}
    started = time.monotonic(); output = bytearray()
    proc = subprocess.Popen([shutil.which('sandbox-exec'), '-p', sandbox_profile, *argv],
                            cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,start_new_session=True)
    try:
        proc.stdin.write(stdin.encode()); proc.stdin.close()
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout,selectors.EVENT_READ)
            while sel.get_map():
                from .automation_control import policy
                if cancelled() or policy()['kill_switch'] or time.monotonic()-started>timeout:
                    raise TimeoutError('Cancelled, killed or timed out')
                for key,_ in sel.select(.1):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:sel.unregister(key.fileobj);continue
                    output.extend(chunk)
                    if len(output)>1024*1024:raise ValueError('Output limit exceeded')
        return {'exit_code':proc.wait(timeout=1), 'output':output.decode(errors='replace')}
    finally:
        # Kill the process group even when the parent exited with children alive.
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait()
