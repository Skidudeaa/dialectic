
import json, sys
from pathlib import Path
book_path = sys.argv[1]
for i, arg in enumerate(sys.argv):
    if arg == "--export-state" and i + 1 < len(sys.argv):
        out = sys.argv[i + 1]
        snap = {"v": 1, "timestamp": "2026-01-01T00:00:00Z", "nodeStates": {}}
        Path(out).write_text(json.dumps(snap))
        break
# Fail only for 'a-fail' book
sys.exit(1 if "a-fail" in book_path else 0)
