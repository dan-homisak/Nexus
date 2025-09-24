from pathlib import Path
from datetime import datetime

VERSIONS_DIR = Path("data/versions")

def ensure_dirs():
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def latest_version_dir():
    ensure_dirs()
    dirs = [p for p in VERSIONS_DIR.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return sorted(dirs)[-1]

def new_version_dir():
    ensure_dirs()
    d = VERSIONS_DIR / timestamp()
    d.mkdir(parents=True, exist_ok=True)
    return d
