import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = DESKTOP_DIR.parent
BACKEND_ROOT = REPO_ROOT / "backend"

for entry in (str(DESKTOP_DIR), str(BACKEND_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
