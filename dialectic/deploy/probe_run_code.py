"""Operator probe (costs one Sonnet turn): run with `python3 deploy/probe_run_code.py` from dialectic/.

Real-model probe: does the participant choose run_code and come back with
real output and a filed artifact? Real Anthropic call, real bwrap, real git;
only the DB is a fake (the attachments INSERT is recorded, not executed)."""
import asyncio, json, os, sys, tempfile, time
from types import SimpleNamespace
from uuid import uuid4
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, "..", ".env"))
# Throwaway workspace and media root; the REAL venv. Nothing touches
# production rows: the DB below records the INSERT instead of running it.
SCRATCH = tempfile.mkdtemp(prefix="dialectic-probe-")
os.environ["DIALECTIC_WORKSHOP_ROOT"] = os.path.join(SCRATCH, "workshop")
os.environ.setdefault("DIALECTIC_WORKSHOP_VENV", "/var/lib/dialectic/workshop/venv")
os.environ["MEDIA_ROOT"] = os.path.join(SCRATCH, "media")

from llm.providers import LLMRequest, ProviderName
from llm.router import ModelRouter
from llm.tool_loop import ToolLoop
from llm.tools import build_registry
from llm import workshop


class FakeDB:
    def __init__(self): self.rows = []
    async def fetchrow(self, query, *args):
        cols = ["id","room_id","message_id","uploader_user_id","kind","mime","bytes","sha256","width","height","original_name","storage_path","created_at"]
        row = dict(zip(cols, [args[0], args[1], None, None, args[2], args[3], args[4], args[5], args[6], args[7], args[8], args[9], args[10]]))
        self.rows.append(row); return row
    async def fetch(self, query, *args): return []


async def main():
    room = SimpleNamespace(id=uuid4(), linked_book_id=None, trading_config=None)
    db = FakeDB()
    registry = build_registry(room, db)
    assert registry.get("run_code") is not None
    router = ModelRouter(primary_provider=ProviderName.ANTHROPIC, fallback_provider=ProviderName.ANTHROPIC,
                         primary_model="claude-sonnet-5", fallback_model="claude-sonnet-5")
    system = (
        "You are Dialectic, the third participant in a private room with Amo and Dan. Answer as a peer, briefly.\n\n"
        "## Your Tools\nWhen computing beats recalling — a backtest, a simulation, a chart, a table from a file someone "
        "dropped, a statistic, arithmetic you would otherwise do in your head — run_code is how you do it. The Workshop is "
        "this room's own persistent sandbox (Python with numpy, pandas and matplotlib; no network); files you write stay for "
        "the next run, and a chart or table you save attaches to your message. Report what the run printed, never what you "
        "expected it to print, and show the number before the interpretation."
    )
    ask = ("@Dialectic simulate 20,000 GBM paths from 100 with 30% annual vol and zero drift over 20 trading days. "
           "Give me the 5th and 95th percentile of the terminal price and save a histogram of the terminal prices as a PNG.")
    request = LLMRequest(messages=[{"role": "user", "content": f"Amo: {ask}"}], system=system, model="claude-sonnet-5", max_tokens=2048)
    t0 = time.monotonic()
    result = await ToolLoop(router, registry).run(request)
    dt = time.monotonic() - t0
    print(f"iterations={result.iterations} degraded={result.degraded} success={result.routing.success} wall={dt:.1f}s")
    for e in result.tool_trace:
        prov = {k: v for k, v in (e.get("provenance") or {}).items() if k not in ("stdout_tail", "stderr_tail")}
        print(f"- {e['name']} ok={e['ok']} latency_ms={e['latency_ms']} error={e.get('error')} provenance={json.dumps(prov)}")
        if e.get("name") == "run_code":
            print("  code:\n" + "\n".join("    " + ln for ln in str((e.get("input") or {}).get("code", "")).splitlines()[:40]))
            print("  stdout_tail:", json.dumps((e.get("provenance") or {}).get("stdout_tail")))
    print("--- final content ---")
    print(result.routing.response.content if result.routing.response else None)
    print("--- attachments filed (fake db) ---")
    for r in db.rows:
        p = os.path.join(os.environ["MEDIA_ROOT"], r["storage_path"])
        print(f"  {r['original_name']} kind={r['kind']} mime={r['mime']} bytes={r['bytes']} dims={r['width']}x{r['height']} on_disk={os.path.isfile(p)}")
    ws = workshop.workspace_dir(room.id)
    code, log = await workshop._git(ws, "log", "--oneline")
    print("--- workspace git log ---\n" + log)

asyncio.run(main())
