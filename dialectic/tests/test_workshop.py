"""run_code — the participant's hands.

Real bubblewrap runs (skipped where bwrap or the Workshop venv is missing),
the fence (no network, nobody's uid, no host secrets), the wall-clock kill,
workspace persistence as git history, the artifact rows a run files
(uploader NULL, message NULL, kind by mime), and the bind that homes them
through documents.document_ids_from_calls.
"""

import os
import shutil
import struct
import zlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from llm import documents, workshop
from llm.tools import build_registry

REAL_VENV = os.path.join(workshop.DEFAULT_ROOT, "venv")

sandbox = pytest.mark.skipif(
    not (shutil.which("bwrap") and shutil.which("prlimit")
         and os.path.isfile(os.path.join(REAL_VENV, "bin", "python"))),
    reason="no bwrap/prlimit or Workshop venv on this host",
)


class FakeDB:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        cols = ["id", "room_id", "message_id", "uploader_user_id", "kind", "mime",
                "bytes", "sha256", "width", "height", "original_name",
                "storage_path", "created_at"]
        # Mirror file_artifacts' INSERT: ($1 id, $2 room, NULL, NULL, $3 kind,
        # $4 mime, $5 bytes, $6 sha, $7 w, $8 h, $9 name, $10 path, $11 ts)
        vals = [args[0], args[1], None, None, args[2], args[3], args[4], args[5],
                args[6], args[7], args[8], args[9], args[10]]
        return dict(zip(cols, vals))

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []


@pytest.fixture
def ws_env(tmp_path, monkeypatch):
    """Workspaces under tmp_path, media under tmp_path, the REAL venv."""
    monkeypatch.setenv("DIALECTIC_WORKSHOP_ROOT", str(tmp_path / "workshop"))
    monkeypatch.setenv("DIALECTIC_WORKSHOP_VENV", REAL_VENV)
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    return tmp_path


def _png_1x1() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")) + chunk(b"IEND", b""))


# ── the fence, pinned on the argv ────────────────────────────────────

def test_bwrap_argv_pins_the_fence(ws_env):
    if not (shutil.which("bwrap") and shutil.which("prlimit")):
        pytest.skip("no bwrap/prlimit")
    ws = workshop.workspace_dir(uuid4())
    argv = workshop.bwrap_argv(ws, ["/opt/venv/bin/python", "x.py"])
    joined = " ".join(argv)
    assert "--unshare-all" in argv and "--share-net" not in argv
    assert "--uid 65534 --gid 65534" in joined
    assert "--ro-bind /usr /usr" in joined
    assert f"--bind {ws} /work" in joined
    assert f"--ro-bind {REAL_VENV} /opt/venv" in joined
    assert "--clearenv" in argv and "--die-with-parent" in argv
    # Only the workspace is bound read-write.
    rw = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert rw == [ws]


def test_workspace_is_a_git_repo_with_runs_dir(ws_env):
    ws = workshop.workspace_dir(uuid4())
    assert os.path.isdir(os.path.join(ws, ".git"))
    assert os.path.isdir(os.path.join(ws, "runs"))


# ── real runs ────────────────────────────────────────────────────────

@sandbox
@pytest.mark.asyncio
async def test_run_returns_stdout_exit_code_and_a_commit(ws_env):
    res = await workshop.run(uuid4(), "print(6 * 7)")
    assert res["stdout"] == "42\n" and res["exit_code"] == 0 and not res["timed_out"]
    assert res["run_dir"].startswith("runs/") and res["commit"] and len(res["commit"]) == 40
    assert res["changed_files"] == []  # the run's own main.py lives under runs/, not an artifact


@sandbox
@pytest.mark.asyncio
async def test_run_has_no_network_no_secrets_and_is_nobody(ws_env):
    code = (
        "import os, socket\n"
        "print('uid', os.getuid())\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=2); print('NET LEAK')\n"
        "except OSError as e: print('net', e.errno)\n"
        "print('shadow', os.path.exists('/etc/shadow'))\n"
        "print('env', os.path.exists('/root/DwoodAmo/dialectic/.env'))\n"
        "try:\n    open('/usr/share/.workshop-probe', 'w'); print('USR WRITABLE')\n"
        "except OSError: print('usr ro')\n"
    )
    res = await workshop.run(uuid4(), code)
    assert "uid 65534" in res["stdout"]
    assert "NET LEAK" not in res["stdout"] and "net 101" in res["stdout"]
    assert "shadow False" in res["stdout"] and "env False" in res["stdout"]
    assert "usr ro" in res["stdout"]


@sandbox
@pytest.mark.asyncio
async def test_run_scientific_stack_and_png_artifact(ws_env):
    room = uuid4()
    code = (
        "import numpy as np, pandas as pd, matplotlib.pyplot as plt\n"
        "x = np.linspace(0, 1, 10); plt.plot(x, x**2); plt.savefig('curve.png', dpi=50)\n"
        "pd.DataFrame({'x': x}).to_csv('curve.csv', index=False); print('done')\n"
    )
    res = await workshop.run(room, code, timeout_s=25)
    assert res["exit_code"] == 0, res["stderr"]
    assert res["changed_files"] == ["curve.csv", "curve.png"]


@sandbox
@pytest.mark.asyncio
async def test_run_timeout_kills_and_reports(ws_env):
    res = await workshop.run(uuid4(), "import time\nprint('start', flush=True)\ntime.sleep(30)", timeout_s=2)
    assert res["timed_out"] is True and res["exit_code"] is None
    assert res["duration_ms"] < 6000
    assert "start" in res["stdout"]


@sandbox
@pytest.mark.asyncio
async def test_workspace_persists_between_runs_as_git_history(ws_env):
    room = uuid4()
    one = await workshop.run(room, "open('helper.py', 'w').write('def f():\\n    return 41\\n')")
    two = await workshop.run(room, "import helper\nprint(helper.f() + 1)")
    assert one["changed_files"] == ["helper.py"]
    assert two["exit_code"] == 0, two["stderr"]
    assert two["stdout"] == "42\n" and two["changed_files"] == []
    code, log = await workshop._git(workshop.workspace_dir(room), "log", "--oneline")
    assert code == 0 and len(log.splitlines()) == 2


@sandbox
@pytest.mark.asyncio
async def test_bash_language(ws_env):
    res = await workshop.run(uuid4(), "echo hi; ls /work", language="bash")
    assert res["exit_code"] == 0 and res["stdout"].startswith("hi\n")


@pytest.mark.asyncio
async def test_run_rejects_bad_input(ws_env):
    with pytest.raises(ValueError):
        await workshop.run(uuid4(), "   ")
    with pytest.raises(ValueError):
        await workshop.run(uuid4(), "print(1)", language="ruby")
    with pytest.raises(ValueError):
        await workshop.run(uuid4(), "x" * (workshop.MAX_CODE_CHARS + 1))


# ── artifacts: the rows a run files ──────────────────────────────────

@pytest.mark.asyncio
async def test_file_artifacts_files_png_as_image_and_csv_as_file(ws_env):
    room = uuid4()
    ws = workshop.workspace_dir(room)
    with open(os.path.join(ws, "chart.png"), "wb") as fh:
        fh.write(_png_1x1())
    with open(os.path.join(ws, "table.csv"), "w") as fh:
        fh.write("a,b\n1,2\n")
    db = FakeDB()
    rows = await workshop.file_artifacts(db, room, ws, ["chart.png", "table.csv"])
    by_name = {r["original_name"]: r for r in rows}
    png, csv = by_name["chart.png"], by_name["table.csv"]
    assert png["kind"] == "image" and png["mime"] == "image/png" and (png["width"], png["height"]) == (1, 1)
    assert csv["kind"] == "file" and csv["mime"] == "text/csv" and csv["width"] is None
    for r in rows:
        assert r["uploader_user_id"] is None and r["message_id"] is None
        assert os.path.isfile(os.path.join(ws_env / "media", r["storage_path"]))
    assert "VALUES ($1, $2, NULL, NULL, $3, $4" in db.calls[0][0]


@pytest.mark.asyncio
async def test_file_artifacts_skips_empty_oversize_and_caps(ws_env, monkeypatch):
    monkeypatch.setenv("MEDIA_MAX_FILE_BYTES", "10")
    room = uuid4()
    ws = workshop.workspace_dir(room)
    open(os.path.join(ws, "empty.txt"), "w").close()
    with open(os.path.join(ws, "big.txt"), "w") as fh:
        fh.write("x" * 11)
    names = []
    for i in range(workshop.ARTIFACT_CAP + 2):
        name = f"f{i}.txt"
        with open(os.path.join(ws, name), "w") as fh:
            fh.write("ok")
        names.append(name)
    rows = await workshop.file_artifacts(FakeDB(), room, ws, ["empty.txt", "big.txt"] + names)
    assert len(rows) == workshop.ARTIFACT_CAP
    assert {r["original_name"] for r in rows} <= set(names)


def test_bind_reads_workshop_attachment_ids_beside_document_attachment_id():
    a, b, c = uuid4(), uuid4(), uuid4()
    calls = [
        {"provenance": {"kind": "workshop", "attachment_ids": [str(a), str(b), "not-a-uuid"]}},
        {"provenance": {"kind": "document", "attachment_id": str(c)}},
        {"provenance": {"kind": "hypothetical", "attachment_ids": [str(uuid4())]}},
    ]
    assert documents.document_ids_from_calls(calls) == [a, b, c]


# ── the tool in the registry ─────────────────────────────────────────

def test_registry_carries_run_code_under_the_timeout_law(ws_env):
    room = SimpleNamespace(id=uuid4(), linked_book_id=None, trading_config=None)
    tool = build_registry(room, FakeDB()).get("run_code")
    assert tool is not None
    assert tool.timeout_s > workshop.RUN_TIMEOUT_MAX_S
    assert tool.input_schema["properties"]["language"]["enum"] == ["python", "bash"]


def test_kill_switch_removes_the_tool(ws_env, monkeypatch):
    monkeypatch.setenv("DIALECTIC_WORKSHOP_ENABLED", "0")
    room = SimpleNamespace(id=uuid4(), linked_book_id=None, trading_config=None)
    assert build_registry(room, FakeDB()).get("run_code") is None


@sandbox
@pytest.mark.asyncio
async def test_tool_returns_workshop_provenance_that_binds(ws_env):
    room = SimpleNamespace(id=uuid4(), linked_book_id=None, trading_config=None)
    db = FakeDB()
    tool = build_registry(room, db).get("run_code")
    out = await tool.execute({"code": "open('out.csv','w').write('a\\n1\\n'); print('ok')"})
    assert out["run"]["exit_code"] == 0 and out["run"]["stdout"] == "ok\n"
    assert [a["filename"] for a in out["artifacts"]] == ["out.csv"]
    prov = out["provenance"]
    assert prov["kind"] == "workshop" and len(prov["attachment_ids"]) == 1
    assert prov["stdout_tail"] == "ok\n" and prov["commit"]
    assert documents.document_ids_from_calls([{"provenance": prov}]) == [UUID(prov["attachment_ids"][0])]
    assert "Attached to your message: out.csv" in out["status"]


@sandbox
@pytest.mark.asyncio
async def test_tool_reports_a_failing_program_as_data_not_error(ws_env):
    room = SimpleNamespace(id=uuid4(), linked_book_id=None, trading_config=None)
    tool = build_registry(room, FakeDB()).get("run_code")
    out = await tool.execute({"code": "import sys\nprint('before')\nsys.exit(3)"})
    assert out["run"]["exit_code"] == 3 and out["run"]["stdout"] == "before\n"
    assert out["provenance"]["attachment_ids"] == []


# ── real Postgres: the image row against the live table shape ────────

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)
PG_ROOM = __import__("uuid").UUID("00000000-0000-4000-8000-00000000b327")


@pytest_asyncio.fixture
async def pg():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) VALUES ($1, now(), 'Workshop Room', 'ws-tok')", PG_ROOM)
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_pg_file_artifacts_inserts_an_llm_authored_image_row(pg, ws_env):
    ws = workshop.workspace_dir(PG_ROOM)
    with open(os.path.join(ws, "chart.png"), "wb") as fh:
        fh.write(_png_1x1())
    rows = await workshop.file_artifacts(pg, PG_ROOM, ws, ["chart.png"])
    assert len(rows) == 1
    row = await pg.fetchrow("SELECT * FROM attachments WHERE id = $1", __import__("uuid").UUID(rows[0]["id"]))
    assert row["kind"] == "image" and row["uploader_user_id"] is None and row["message_id"] is None
    assert (row["width"], row["height"]) == (1, 1)
