# WHY: v2 persistence layer. SQLite with WAL mode replaces file-based
# JSON/JSONL state in web/state.py. All Repository methods are synchronous
# — callers wrap in asyncio.to_thread().
