from pathlib import Path

APP_DIR = Path.home() / "Library" / "Application Support" / "gtasks-sync"
QUEUE_DIR = APP_DIR / "queue"
CACHE_FILE = APP_DIR / "cache.json"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "gtasks-sync.log"
# launchd sends stdout/stderr here: crashes before logging starts, and hang tracebacks.
LAUNCHD_LOG_FILE = Path.home() / "Library" / "Logs" / "gtasks-sync.launchd.log"
