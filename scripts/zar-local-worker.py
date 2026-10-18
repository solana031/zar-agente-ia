"""Run using the dedicated local environment, without loading provider secrets."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.instagram_local_worker import main
if __name__ == '__main__':
    main()
