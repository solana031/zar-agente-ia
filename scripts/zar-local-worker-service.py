"""User-session supervisor. No Codex runtime, no listener, no remote commands."""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    os.chdir(ROOT)
    while True:
        try:
            subprocess.run([sys.executable,str(ROOT/'scripts/zar-local-worker.py')],cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError:pass
        time.sleep(30)
