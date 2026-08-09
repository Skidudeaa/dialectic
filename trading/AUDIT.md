# AUDIT.md — Full Codebase Audit

Generated: 2026-04-07T21:31Z

---

## 1. Directory Tree

```
tradingDesk/
├── CLAUDE.md
├── INTEGRATION.md
├── PROJECT.md
├── README.md
├── Screenshot_20260405-163602.png
├── active-commodity-book-full.png
├── active-commodity-book-pos0-0px.png
├── active-commodity-book-pos1-900px.png
├── active-commodity-book-pos2-1800px.png
├── active-commodity-book-pos3-2700px.png
├── active-commodity-book-pos4-3600px.png
├── active-commodity-book-pos5-4500px.png
├── active-commodity-book-pos6-5400px.png
├── active-commodity-book-pos7-6400px.png
├── active-commodity-book.html
├── .claude/
│   ├── settings.json
│   └── settings.local.json
├── .gitignore
├── .mcp.json
├── .planning/
│   ├── intel/
│   │   ├── graph.db
│   │   ├── history.json
│   │   ├── summary.md
│   │   └── zoekt/index/
│   └── tv-plan/
│       ├── codebase-map.md
│       ├── judge-verdict.md
│       ├── plan-alpha-v1.md
│       ├── plan-alpha-v2.md
│       ├── plan-bravo-v1.md
│       ├── plan-bravo-v2.md
│       ├── red-team-alpha.md
│       ├── red-team-bravo.md
│       └── research-context.md
├── .playwright-mcp/
│   └── (console logs, screenshots, page snapshots — 30+ files)
├── .pytest_cache/
├── books/
│   ├── iran-hormuz-2026.json
│   ├── iran-hormuz-graph.json
│   └── trump-tariffs-graph.json
├── docs/
│   ├── brainstorms/
│   │   ├── 2026-03-31-multi-book-runner-requirements.md
│   │   └── 2026-03-31-trading-desk-web-ui-requirements.md
│   ├── ideation/
│   │   └── 2026-03-31-dialectic-collaboration-ideation.md
│   ├── plans/
│   │   ├── 2026-03-30-001-feat-dialectic-trading-room-integration-plan.md
│   │   ├── 2026-03-31-001-fix-48h-review-findings-plan.md
│   │   ├── 2026-03-31-002-feat-trading-desk-web-ui-plan.md
│   │   ├── 2026-03-31-003-feat-multi-book-runner-plan.md
│   │   └── 2026-04-05-001-feat-tradingview-integration-plan.md
│   ├── solutions/
│   │   └── security-issues/
│   │       └── xss-in-generated-html-from-json-config-2026-03-31.md
│   └── trading-desk-overview.md
├── outcomes/
│   ├── open_trades.json
│   └── trades/
│       ├── TRD-CF-PLANTING.jsonl
│       ├── TRD-SH-RECESSION.jsonl
│       └── TRD-XOP-HORMUZ.jsonl
├── output/
│   ├── iran-hormuz-graph.html
│   ├── iran-hormuz.html
│   ├── trading-desk-infographic.html
│   └── trump-tariffs-graph.html
├── research/
│   ├── api-reference.md
│   ├── architecture-decisions.md
│   ├── bookgen-lessons.md
│   └── economic-transmission.md
├── snapshots/
│   ├── iran-hormuz-graph-latest.json
│   ├── iran-hormuz-graph-prev.json
│   ├── test.json
│   ├── trump-tariffs-graph-latest.json
│   └── trump-tariffs-graph-prev.json
├── tools/
│   ├── bridge/
│   │   ├── diff_snapshots.py
│   │   ├── push_to_dialectic.py
│   │   ├── run-all.py
│   │   ├── test_diff.py
│   │   ├── test_push.py
│   │   └── test_run_all.py
│   ├── commodity-book/
│   │   ├── bookgen.py
│   │   └── iran-hormuz-2026.json
│   ├── data_fetch/
│   │   ├── .gitkeep
│   │   ├── polymarket.py
│   │   └── test_polymarket.py
│   ├── outcomes/
│   │   ├── cross_book.py
│   │   ├── e2e_integration.py
│   │   ├── lifecycle_monitor.py
│   │   ├── log_entry.py
│   │   ├── morning_brief.py
│   │   ├── test_cross_book_brief.py
│   │   └── test_lifecycle_monitor.py
│   ├── polymarket/
│   │   └── .gitkeep
│   ├── signals/
│   │   └── .gitkeep
│   ├── thesis_graph/
│   │   ├── lib/
│   │   │   ├── cytoscape-dagre.js
│   │   │   ├── cytoscape.min.js
│   │   │   └── dagre.min.js
│   │   ├── test_export.py
│   │   └── thesisgraph.py
│   └── validation/
│       ├── e2e_test.py
│       └── mock_dialectic.py
└── venv/  (Python 3.12 virtual environment — pip, pytest, etc.)
```

---

## 2. Python Files — Imports, Classes, Functions

### tools/thesis_graph/thesisgraph.py (~2300 lines)

**Imports:**
```python
import argparse
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
```

**Module-level constants:**
```python
REQUIRED_TOP = ["meta", "nodes", "edges"]
REQUIRED_NODE = ["id", "label", "type"]
REQUIRED_EDGE = ["from", "to", "strength"]
VALID_NODE_TYPES = {"event", "price", "indicator", "deadline", "gate", "constraint", "conditional", "reversal"}
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
```

**Functions:**
```python
def load_config(path: str) -> dict
def validate_config(cfg: dict) -> tuple[list[str], list[str]]
def topo_sort(nodes: list, edges: list) -> list[str]
def eval_node_state(node: dict, upstream_states: dict, edges: list) -> str
def propagate(cfg: dict) -> dict
def score_confluence(cfg: dict, states: dict) -> dict
def parse_lag_days(lag_str: str, ref_date: date | None = None) -> int
def propagate_at_horizon(cfg: dict, horizon_days: int, ref_date: date | None = None) -> dict
def get_current_phase(cfg: dict) -> tuple[int, str]
def eval_scenario(cfg: dict, scenario: dict, base_states: dict = None) -> tuple[dict, dict]
def export_state(cfg: dict, states: dict, confluence: dict, phase_num: int, phase_key: str, scenarios_result: list[tuple[dict, dict, dict]], today: date | None = None) -> dict
def fetch_prices(cfg: dict, retries: int = 2) -> dict
def update_config_file(config_path: str, cfg: dict) -> None
def fetch_polymarket(cfg: dict) -> dict
def build_nodes_js(cfg: dict) -> str
def build_edges_js(cfg: dict) -> str
def build_instruments_js(cfg: dict) -> str
def build_scenarios_js(cfg: dict) -> str
def build_cascade_js(cfg: dict) -> str
def build_analogs_js(cfg: dict) -> str
def build_topo_order_js(cfg: dict) -> str
def build_fetch_syms_js(cfg: dict) -> str
def build_defaults_js(cfg: dict) -> str
def find_skill_script(name: str) -> str | None
def run_validate(html_path: str) -> bool
def run_screenshot(html_path: str, output_dir: str = ".") -> str | None
def run_publish(html_path: str, cfg: dict, args) -> None
def generate_html(cfg: dict) -> str
def get_template() -> str
def print_summary(cfg: dict, file=None) -> None
def main()
```

---

### tools/bridge/diff_snapshots.py

**Imports:**
```python
import argparse
import json
import sys
from pathlib import Path
```

**Functions:**
```python
def load_snapshot(path: str) -> dict
def diff_node_states(old: dict, new: dict) -> tuple[list, list, list]
def diff_confluence(old: dict, new: dict) -> dict
def diff_countdowns(old: dict, new: dict) -> list
def diff_markets(old: dict, new: dict) -> dict
def build_delta(old: dict, new: dict) -> dict
def main()
```

---

### tools/bridge/push_to_dialectic.py

**Imports:**
```python
import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
```

**Functions:**
```python
def get_room_token() -> str
def check_transport_security(url: str) -> None
def load_snapshot(source: str) -> bytes
def push_snapshot(dialectic_url: str, room_id: str, token: str, payload: bytes, max_attempts: int = 3) -> None
def build_parser() -> argparse.ArgumentParser
def main()
```

---

### tools/bridge/run-all.py

**Imports:**
```python
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
```

**Module-level constants:**
```python
ROOT: Path = Path(__file__).resolve().parent.parent.parent
THESISGRAPH: str = str(ROOT / "tools" / "thesis_graph" / "thesisgraph.py")
DIFF_SNAPSHOTS: str = str(ROOT / "tools" / "bridge" / "diff_snapshots.py")
PUSH_SCRIPT: str = str(ROOT / "tools" / "bridge" / "push_to_dialectic.py")
```

**Functions:**
```python
def load_book(path: Path) -> Optional[dict]
def discover_books(books_dir: Path) -> list
def run_export(book_path: Path, latest: Path) -> int
def run_diff(prev: Path, latest: Path) -> int
def run_push(latest: Path, room_id: str, room_token: str) -> int
def run_book(book_id: str, book_path: Path, book_data: dict, snapshots_dir: Path, dry_run: bool) -> dict
def build_parser() -> argparse.ArgumentParser
def main() -> None
```

---

### tools/data_fetch/polymarket.py

**Imports:**
```python
import json
import sys
import time
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
```

**Module-level constants:**
```python
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 2
RETRY_DELAY = 1.5
_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/polymarket-fetcher)"}
```

**Classes:**
```python
class PolymarketError(Exception)
class MarketNotFoundError(PolymarketError)
class APIError(PolymarketError)
```

**Functions:**
```python
def _make_request(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes
def _parse_outcome_prices(raw_prices: str, outcomes: list) -> Optional[float]
def _search_events(query: str, timeout: int = DEFAULT_TIMEOUT) -> list
def _search_markets(query: str, timeout: int = DEFAULT_TIMEOUT) -> list
def _extract_probability_from_market(market: dict) -> Optional[float]
def _match_market_in_results(results: list, slug: str) -> Optional[dict]
def fetch_single_market(slug: str, timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES) -> Tuple[str, Optional[float]]
def fetch_markets(slugs: List[str], timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES) -> Dict[str, Optional[float]]
def main() -> None
```

---

### tools/commodity-book/bookgen.py (~900 lines)

**Imports:**
```python
import argparse
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
```

**Module-level constants:**
```python
REQUIRED_TOP = ["title", "monthlyBudget", "instruments", "triggers", "rules", "marketFields"]
REQUIRED_INST = ["id", "monthly", "role", "category", "ref"]
REQUIRED_TRIG = ["id", "name", "action", "detail", "context"]
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
```

**Functions:**
```python
def load_config(path: str) -> dict
def validate_config(cfg: dict) -> tuple[list[str], list[str]]
def fetch_prices(cfg: dict, retries: int = 2) -> dict
def update_config_file(config_path: str, cfg: dict) -> None
def inst_to_js(inst: dict) -> dict
def trig_to_js(t: dict) -> dict
def overlay_to_js(o: dict) -> dict
def mkt_to_js(m: dict) -> dict
def build_category_css(cats: dict) -> str
def build_cats_js(cats: dict) -> str
def build_defaults_js(cfg: dict) -> str
def build_fetch_syms_js(cfg: dict) -> str
def build_situation_html(cfg: dict) -> str
def build_provenance_html(cfg: dict) -> str
def generate_html(cfg: dict) -> str
def find_skill_script(name: str) -> str | None
def run_validate(html_path: str) -> bool
def run_screenshot(html_path: str, output_dir: str = ".") -> str | None
def run_publish(html_path: str, cfg: dict, args) -> None
def get_template() -> str
def print_summary(cfg: dict) -> None
def main()
```

---

### tools/validation/mock_dialectic.py

**Imports:**
```python
import argparse
import json
import re
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
```

**Module-level constants:**
```python
REQUIRED_SNAPSHOT_KEYS = {"v", "timestamp", "title", "nodeStates", "confluenceScores", "cascadePhase", "countdowns", "marketSnapshot", "scenarioImpacts", "portfolioSummary"}
SNAPSHOT_PATH_RE = re.compile(r"^/rooms/([^/]+)/trading/snapshot$")
```

**Classes:**
```python
class ReceivedSnapshot:
    def __init__(self, room_id: str, payload: dict, auth_header: str, content_type: str, user_agent: str) -> None
    def to_dict(self) -> dict

class MockDialecticHandler(BaseHTTPRequestHandler):
    received: list[ReceivedSnapshot]
    lock: threading.Lock
    forced_status_code: Optional[int]
    def log_message(self, format: str, *args) -> None
    def _send_json(self, code: int, body: dict) -> None
    def do_POST(self) -> None
    def do_GET(self) -> None
```

**Functions:**
```python
def create_server(port: int = 0) -> HTTPServer
def start_server_thread(port: int = 0) -> tuple[HTTPServer, threading.Thread]
def get_received_snapshots() -> list[ReceivedSnapshot]
def clear_received_snapshots() -> None
def force_next_status(code: int) -> None
def main() -> None
```

---

### tools/outcomes/lifecycle_monitor.py (~706 lines)

**Imports:**
```python
import json
import hashlib
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Union, Tuple, Any
```

**Dataclasses:**
```python
@dataclass
class ProvenanceTag:
    variable: str
    value: float
    unvalidated_assumption: str
    confidence_level: str  # "INERT" | "UNVERIFIED" | "VALIDATED"

@dataclass
class TargetRefusal:
    reason: str
    contaminants: List[str]
    fix_required: str

@dataclass
class DynamicTarget:
    baseline_ref: float
    prob_weighted_net_impact: float
    computed_target: float
    provenance: List[ProvenanceTag]

@dataclass
class Predicate:
    kind: str
    node_id: str = ""
    expected: str = ""
    allowed: List[str] = field(default_factory=list)
    path: str = ""
    op: str = ""
    value: float = 0.0
    days: int = 0
    load_bearing: bool = True

@dataclass
class EvaluatedPredicate:
    predicate: Predicate
    actual: Any = None
    is_flipped: bool = False
    note: str = ""

@dataclass
class PostExitVerdict:
    trade_id: str
    exit_timestamp: str
    predicate_consistency: float
    load_bearing_flipped: List[str]
    supporting_flipped: List[str]
    realized_vs_predicted: str
    recommended_weight_adjustments: Dict[str, float]
    adjustment_provenance: str

@dataclass
class TradeRecord:
    trade_id: str
    ticker: str
    event_type: str  # "ENTRY" | "EVALUATION" | "DEGRADED" | "EXIT"
    snapshot_hash: str
    evaluated_predicates: List[EvaluatedPredicate]
    run_id: str
    timestamp: str = ""
    dynamic_target: Optional[DynamicTarget] = None
    target_refusal: Optional[TargetRefusal] = None
    verdict: Optional[PostExitVerdict] = None
```

**Classes:**
```python
class Snapshot:
    REQUIRED_KEYS = {"nodeStates", "confluenceScores", "cascadePhase", "countdowns", "marketSnapshot"}
    def __init__(self, data: dict, path: Optional[Path] = None)
    @classmethod
    def load(cls, path: Path) -> "Snapshot"
    def content_hash(self) -> str
    def get_path(self, dotted_path: str) -> Optional[Any]
    def get_countdown_days(self, node_id: str) -> Optional[int]

class LedgerAnalyzer:
    MIN_SAMPLES = 10
    def __init__(self, ledger_dir: Path)
    def _iter_records(self)
    def node_flip_rate(self, node_id: str) -> Tuple[float, int]
    def empirical_weight_adjustment(self, node_id: str) -> Tuple[float, str]

class PredicateLifecycleMonitor:
    def __init__(self, ledger_dir: str = "/root/tradingDesk/outcomes/trades")
    def _compute_run_id(self, trade_id: str, snapshot_hash: str, predicates: List[Predicate]) -> str
    def _find_existing(self, trade_id: str, run_id: str) -> Optional[TradeRecord]
    def _log(self, record: TradeRecord) -> None
    def _weighted_consistency(self, evaluated: List[EvaluatedPredicate], snapshot: Snapshot) -> float
    def run_evaluation_cycle(self, trade_id: str, ticker: str, predicates: List[Predicate], snapshot_path: Path, ref_price: Optional[float] = None, book_path: Optional[Path] = None) -> Tuple[str, TradeRecord]
```

**Module-level trade gates:**
```python
XOP_GATE: List[Predicate]  # 4 predicates — em-stress state, confluence threshold, brent state_set, planting countdown
CF_GATE: List[Predicate]   # 3 predicates — planting-miss state, countdown, scenario netImpact threshold
SPY_SHORT_GATE: List[Predicate]  # 4 predicates — earnings, consumer, recession confluence thresholds, fed state_set
```

**Functions:**
```python
def _serialize_record(record: TradeRecord) -> str
def _deserialize_record(line: str) -> Optional[TradeRecord]
def evaluate_predicate(pred: Predicate, snapshot: Snapshot) -> EvaluatedPredicate
def detect_inert_fields(book_path: Path) -> List[ProvenanceTag]
def compute_provenance_target(ref_price: float, scenario_impacts: Dict[str, Dict[str, float]], book_path: Optional[Path] = None) -> Union[DynamicTarget, TargetRefusal]
def step7_evaluate_open_trades(snapshot_path: Path, open_trades_path: Path, book_id: str = "", book_path: Optional[Path] = None, ledger_dir: str = "/root/tradingDesk/outcomes/trades") -> Dict[str, str]
```

---

### tools/outcomes/cross_book.py

**Imports:**
```python
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import sys
from lifecycle_monitor import Snapshot
```

**Dataclasses:**
```python
@dataclass
class CrossBookFlag:
    flag_type: str  # "phase_alignment", "shared_market", "cross_confluence", "compound_recession"
    severity: str   # "HIGH", "MEDIUM", "LOW"
    books: List[str]
    detail: str
    data: Dict = field(default_factory=dict)

@dataclass
class CrossBookReport:
    timestamp: str
    books_analyzed: List[str]
    flags: List[CrossBookFlag]
    shared_markets: Dict[str, Dict[str, float]]
    phase_summary: Dict[str, dict]
```

**Functions:**
```python
def _detect_phase_alignment(snapshots: Dict[str, Snapshot]) -> List[CrossBookFlag]
def _detect_shared_markets(snapshots: Dict[str, Snapshot]) -> Tuple[Dict[str, Dict[str, float]], List[CrossBookFlag]]
def _detect_cross_confluence(snapshots: Dict[str, Snapshot]) -> List[CrossBookFlag]
def _detect_countdown_pressure(snapshots: Dict[str, Snapshot]) -> List[CrossBookFlag]
def scan_cross_book(snapshots_dir: Path, book_ids: Optional[List[str]] = None) -> CrossBookReport
def save_cross_book_flags(report: CrossBookReport, output_path: Path) -> None
```

---

### tools/outcomes/log_entry.py

**Imports:**
```python
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
from lifecycle_monitor import (Predicate, EvaluatedPredicate, TradeRecord, XOP_GATE, CF_GATE, SPY_SHORT_GATE, _serialize_record)
```

**Module-level constants:**
```python
TRADES = {
    "xop": {"trade_id": "TRD-XOP-HORMUZ", "ticker": "XOP", "predicates": XOP_GATE, "ref_price": 188.18, "book": "iran-hormuz-graph"},
    "cf": {"trade_id": "TRD-CF-PLANTING", "ticker": "CF", "predicates": CF_GATE, "ref_price": 136.45, "book": "iran-hormuz-graph"},
    "spy-short": {"trade_id": "TRD-SH-RECESSION", "ticker": "SH", "predicates": SPY_SHORT_GATE, "ref_price": 15.50, "book": "trump-tariffs-graph"},
}
```

**Functions:**
```python
def seed_entry(trade_key: str, ref_price: float | None, ledger_dir: Path) -> None
def write_open_trades_json(ledger_dir: Path) -> None
def main() -> None
```

---

### tools/outcomes/morning_brief.py

**Imports:**
```python
import json
import sys
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Dict, List, Optional
from lifecycle_monitor import Snapshot, LedgerAnalyzer, _deserialize_record
from cross_book import scan_cross_book, CrossBookReport
```

**Functions:**
```python
def _phase_label(phase: dict) -> str
def _format_countdown(cd: dict) -> str
def _format_horizon_trace(trace: dict, node_states_t0: dict) -> List[str]
def _format_ledger_summary(ledger_dir: Path) -> List[str]
def generate_brief(snapshots_dir: Path, ledger_dir: Path, book_ids: Optional[List[str]] = None) -> str
```

---

### tools/outcomes/e2e_integration.py

**Imports:**
```python
import sys, json, tempfile, os
from pathlib import Path
from lifecycle_monitor import (PredicateLifecycleMonitor, Snapshot, XOP_GATE, CF_GATE, SPY_SHORT_GATE, evaluate_predicate, compute_provenance_target, detect_inert_fields, _serialize_record, _deserialize_record, step7_evaluate_open_trades)
from thesisgraph import propagate, score_confluence, propagate_at_horizon, parse_lag_days
from datetime import date
```

**Functions:**
```python
def check(label, condition, detail="")
```

(Script-style test — not pytest, runs sequentially with global error counter)

---

### tools/thesis_graph/test_export.py (76 tests)

**Imports:**
```python
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
import pytest
# Imports from thesisgraph: export_state, propagate, score_confluence, get_current_phase, eval_scenario, eval_node_state, topo_sort
```

**Test classes:**
```python
class TestExportStateFunction (13 tests)
class TestExportStateEdgeCases (4 tests)
class TestCLIExportState (6 tests)
class TestEvalNodeState (39 tests: event, price, indicator, deadline, gate, constraint, conditional, reversal)
```

---

### tools/bridge/test_diff.py (21 tests)

**Imports:**
```python
import json
import subprocess
import sys
from pathlib import Path
import pytest
```

**Test classes:**
```python
class TestStateChanges (2 tests)
class TestIdenticalSnapshots (1 test)
class TestMarketChanges (3 tests)
class TestConfluenceChanges (1 test)
class TestCountdownChanges (1 test)
class TestNodeAddedRemoved (3 tests)
class TestErrorPaths (4 tests)
class TestEdgeCases (6 tests)
```

---

### tools/bridge/test_push.py (26 tests)

**Imports:**
```python
import io
import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
# Imports from push-to-dialectic: get_room_token, check_transport_security, load_snapshot, push_snapshot, build_parser
```

**Test classes:**
```python
class TestGetRoomToken (4 tests)
class TestTransportSecurity (4 tests)
class TestLoadSnapshot (5 tests)
class TestPushSnapshotRequestFormat (5 tests)
class TestPushSnapshotErrors (3 tests)
class TestCLIParsing (4 tests)
class TestEndToEndWithMockServer (1 test)
```

---

### tools/bridge/test_run_all.py (20 tests)

**Imports:**
```python
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
import run_all
```

**Test classes:**
```python
class TestBookDiscovery (4 tests)
class TestHappyPath (3 tests)
class TestConfiguration (4 tests)
class TestFailureHandling (5 tests)
class TestDryRun (2 tests)
class TestSnapshotRotation (2 tests)
```

---

### tools/data_fetch/test_polymarket.py (41 tests)

**Imports:**
```python
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from polymarket import (_parse_outcome_prices, _extract_probability_from_market, _match_market_in_results, fetch_single_market, fetch_markets)
```

**Test classes:**
```python
class TestParseOutcomePrices (16 tests)
class TestExtractProbability (6 tests)
class TestMatchMarket (5 tests)
class TestFetchSingleMarket (7 tests)
class TestFetchMarkets (3 tests)
class TestAPIEdgeCases (4 tests)
```

---

### tools/validation/e2e_test.py (39 tests)

**Imports:**
```python
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest
from mock_dialectic import (start_server_thread, get_received_snapshots, clear_received_snapshots, force_next_status, MockDialecticHandler, REQUIRED_SNAPSHOT_KEYS)
```

**Test classes:**
```python
class TestSnapshotGeneration (7 tests)
class TestSnapshotDiff (7 tests)
class TestPushToMock (4 tests)
class TestFullPipeline (2 tests)
class TestErrorCases (8 tests)
class TestMockServerBehavior (4 tests)
class TestCriticalFixes (5 tests + 2 lifecycle monitor tests)
```

---

### tools/outcomes/test_lifecycle_monitor.py

**Imports:**
```python
import json
import pytest
from pathlib import Path
from dataclasses import asdict
from datetime import date
import sys
from lifecycle_monitor import (Snapshot, Predicate, EvaluatedPredicate, TradeRecord, ProvenanceTag, DynamicTarget, TargetRefusal, PostExitVerdict, evaluate_predicate, compute_provenance_target, detect_inert_fields, LedgerAnalyzer, PredicateLifecycleMonitor, XOP_GATE, CF_GATE, SPY_SHORT_GATE, _serialize_record, _deserialize_record)
```

**Test classes:**
```python
class TestSnapshotLoading (6 tests)
class TestPredicateEvaluation (12 tests)
class TestThreeTradesAgainstRealSnapshots (3 tests)
class TestProvenance (4 tests)
class TestSerialization (1 test)
class TestDedup (2 tests)
class TestLifecycleMonitor (5 tests)
class TestLedgerAnalyzer (3 tests)
class TestPropagationRepair (4 tests: amplification wired, defaults, lag parsing, horizon propagation)
```

---

### tools/outcomes/test_cross_book_brief.py

**Imports:**
```python
import json
import pytest
from pathlib import Path
from datetime import date
import sys
from cross_book import scan_cross_book, CrossBookReport, CrossBookFlag, save_cross_book_flags
from morning_brief import generate_brief
from lifecycle_monitor import Snapshot
```

**Test classes:**
```python
class TestCrossBookScanner (9 tests)
class TestMorningBrief (7 tests)
class TestSnapshotV2 (1 test)
```

---

## 3. JS/TS Files

### tools/thesis_graph/lib/cytoscape.min.js
- Minified Cytoscape.js library (graph visualization)
- No exports — inlined into generated HTML

### tools/thesis_graph/lib/cytoscape-dagre.js
- Cytoscape.js Dagre layout plugin
- No exports — inlined into generated HTML

### tools/thesis_graph/lib/dagre.min.js
- Minified Dagre layout algorithm
- No exports — inlined into generated HTML

No custom JS/TS files exist. All JavaScript is embedded within the Python HTML generators (thesisgraph.py and bookgen.py).

---

## 4. Package Dependencies

### No requirements.txt, pyproject.toml, setup.py, setup.cfg, Pipfile, or package.json exist.

The project explicitly enforces **zero external Python dependencies** (stdlib only). The venv contains:

```
pip (bundled with Python 3.12)
pytest (test runner)
```

Packages present in venv (from pip freeze):
```
(venv contains pip-installed packages including pytest, asyncpg, httpx, openai, tiktoken, click, email-validator, pycparser — these are NOT project dependencies; they are residual from other work or pytest plugins)
```

---

## 5. Environment Variables

### Project-specific env vars referenced in codebase:

| Variable | File | Usage |
|---|---|---|
| `DIALECTIC_ROOM_TOKEN` | `tools/bridge/push_to_dialectic.py:46` | Room auth token for Dialectic API. Read via `os.environ.get("DIALECTIC_ROOM_TOKEN", "").strip()`. Required for push operations. |
| `DIALECTIC_ROOM_TOKEN` | `tools/bridge/run-all.py:165` | Injected into subprocess env: `env = {**os.environ, "DIALECTIC_ROOM_TOKEN": room_token}` |
| `DIALECTIC_ROOM_TOKEN` | `tools/bridge/run-all.py:219` | Fallback: `meta.get("dialecticRoomToken") or os.environ.get("DIALECTIC_ROOM_TOKEN", "")` |
| `os.environ.copy()` | `tools/thesis_graph/thesisgraph.py:1067` | Passed to subprocess for screenshot/publish pipeline |
| `os.environ.copy()` | `tools/commodity-book/bookgen.py:664` | Passed to subprocess for screenshot/publish pipeline |
| `os.environ.copy()` | `tools/validation/e2e_test.py` (multiple) | Used in subprocess calls for E2E tests |

### No `.env`, `.env.example`, or `.env.sample` files exist.

---

## 6. Database

### No database.

No schema definitions, migration files, or ORM models exist. All data is stored as:
- JSON config files (`books/*.json`)
- JSON snapshot files (`snapshots/*.json`)
- JSONL ledger files (`outcomes/trades/*.jsonl`)

---

## 7. API Routes

### Mock Dialectic Server (`tools/validation/mock_dialectic.py`)

| Method | Path | Handler | Request Type | Response Type |
|---|---|---|---|---|
| POST | `/rooms/{room_id}/trading/snapshot` | `MockDialecticHandler.do_POST` | JSON body (snapshot), `Authorization: Bearer <token>` | `{"status": "ok", "room_id": str, "snapshot_version": int, "nodes_received": int}` |
| GET | `/snapshots` | `MockDialecticHandler.do_GET` | none | `{"count": int, "snapshots": list}` |

### Dialectic Integration (outbound, not served)

| Method | Path | Script |
|---|---|---|
| POST | `{dialectic_url}/rooms/{room_id}/trading/snapshot` | `tools/bridge/push_to_dialectic.py` |

### External APIs consumed:

| Service | URL | Script |
|---|---|---|
| Yahoo Finance | `https://query1.finance.yahoo.com/v7/finance/spark?symbols=...&range=1d&interval=1d` | `thesisgraph.py`, `bookgen.py` |
| Polymarket Gamma | `https://gamma-api.polymarket.com/events?slug=...` | `polymarket.py` |
| Polymarket Gamma | `https://gamma-api.polymarket.com/markets?slug=...&active=true&closed=false` | `polymarket.py` |

---

## 8. WebSocket

No WebSocket handlers, message types, or protocols exist in the codebase.

---

## 9. Frontend Pages/Routes

No frontend routing framework. All output is **static generated HTML files**:

| Output File | Generator | Description |
|---|---|---|
| `output/iran-hormuz-graph.html` | `thesisgraph.py` | Interactive causal DAG dashboard (Cytoscape.js) with 5 tabs: Graph, Cascade, Scenarios, Portfolio, Journal |
| `output/trump-tariffs-graph.html` | `thesisgraph.py` | Same format, Trump tariffs thesis |
| `output/iran-hormuz.html` | `bookgen.py` | Legacy commodity book dashboard |
| `output/trading-desk-infographic.html` | (manually created) | Static infographic |

All HTML files are self-contained single-file outputs with inlined CSS, JS (Cytoscape.js ~500KB), and data.

---

## 10. Config Files

### .gitignore
```
__pycache__/
*.pyc
.env
.DS_Store
```

### .mcp.json
```json
{
  "mcpServers": {
    "sextant": {
      "type": "stdio",
      "command": "sextant",
      "args": [
        "mcp"
      ]
    }
  }
}
```

### .claude/settings.json
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "sextant hook sessionstart"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "sextant hook refresh"
          }
        ]
      }
    ]
  }
}
```

### .claude/settings.local.json
```json
{
  "permissions": {
    "allow": [
      "WebFetch(domain:api.supadata.ai)",
      "WebFetch(domain:www.google.com)",
      "WebFetch(domain:api.github.com)",
      "WebFetch(domain:www.youtube.com)",
      "WebFetch(domain:query1.finance.yahoo.com)"
    ]
  }
}
```

### No Dockerfile, docker-compose, or YAML/TOML config files exist.

---

## 11. Entry Points

### CLI commands:

| Command | Script | Description |
|---|---|---|
| `python3 tools/thesis_graph/thesisgraph.py <config.json> -o <output.html>` | thesisgraph.py | Generate interactive DAG dashboard |
| `python3 tools/thesis_graph/thesisgraph.py <config.json> --fetch` | thesisgraph.py | Fetch live Yahoo Finance + Polymarket prices |
| `python3 tools/thesis_graph/thesisgraph.py <config.json> --export-state <file.json>` | thesisgraph.py | Export evaluated graph state as JSON |
| `python3 tools/thesis_graph/thesisgraph.py <config.json> --dry-run` | thesisgraph.py | Validate + propagate, no output |
| `python3 tools/commodity-book/bookgen.py <config.json> -o <output.html>` | bookgen.py | Generate legacy commodity book dashboard |
| `python3 tools/bridge/run-all.py` | run-all.py | Run full pipeline for all thesis books |
| `python3 tools/bridge/run-all.py --dry-run` | run-all.py | Preview pipeline without executing |
| `python3 tools/bridge/run-all.py --books <dir>` | run-all.py | Custom books directory |
| `python3 tools/bridge/diff_snapshots.py <old.json> <new.json>` | diff_snapshots.py | Structured delta between snapshots |
| `python3 tools/bridge/push_to_dialectic.py --snapshot <file> --room-id <uuid>` | push_to_dialectic.py | Push snapshot to Dialectic room |
| `python3 tools/data_fetch/polymarket.py <slug> [--json]` | polymarket.py | Fetch Polymarket prediction probabilities |
| `python3 tools/validation/mock_dialectic.py [--port 8002]` | mock_dialectic.py | Start mock Dialectic server |
| `python3 tools/outcomes/log_entry.py --trade <xop\|cf\|spy-short>` | log_entry.py | Seed ENTRY event into trade ledger |
| `python3 tools/outcomes/log_entry.py --list` | log_entry.py | List available trades |
| `python3 tools/outcomes/log_entry.py --all` | log_entry.py | Seed all trades + write open_trades.json |
| `python3 tools/outcomes/log_entry.py --write-open-trades` | log_entry.py | Write outcomes/open_trades.json |
| `python3 tools/outcomes/morning_brief.py` | morning_brief.py | Generate plain-text morning brief |
| `python3 tools/outcomes/cross_book.py --snapshots-dir <dir>` | cross_book.py | Cross-book confluence scanner |
| `python3 tools/outcomes/e2e_integration.py` | e2e_integration.py | Script-style E2E test (not pytest) |

### Test runner:

```bash
python3 -m pytest tools/thesis_graph/test_export.py tools/bridge/test_diff.py tools/bridge/test_push.py tools/bridge/test_run_all.py tools/data_fetch/test_polymarket.py tools/validation/e2e_test.py -q
```

---

## 12. Current State

### Thesis Graph Engine (dry run):
```
Loading: books/iran-hormuz-graph.json
  Valid (0 warning(s))

  Title:       Iran/Hormuz Thesis — March 2026
  As Of:       2026-03-29
  Nodes:       16 (conditional, constraint, deadline, event, gate, indicator, price, reversal)
  Edges:       14
  Instruments: 10 across 7 node groups
  Scenarios:   4
  Phase:       3 (amplification)

  FIRED:       hormuz, dxy-stress, diesel, em-currency, freight, employment, em-stress, demand-destruction
  APPROACHING: brent, fert-shortage, planting-miss, food-spike

  Confluence:
    em-stress             1.67

  --dry-run: no HTML generated.
```

### Multi-Book Runner (dry run):
```
[dry-run] iran-hormuz-graph: room=56ba2f1e-5c70-4290-a77d-52404f0095da  snapshot=/root/tradingDesk/snapshots/iran-hormuz-graph-latest.json  prev=/root/tradingDesk/snapshots/iran-hormuz-graph-prev.json
[dry-run] trump-tariffs-graph: room=8adcabb7-817a-4802-87c6-3bfd42e6a9eb  snapshot=/root/tradingDesk/snapshots/trump-tariffs-graph-latest.json  prev=/root/tradingDesk/snapshots/trump-tariffs-graph-prev.json
```

### Commodity Book (dry run):
```
Loading: books/iran-hormuz-2026.json
  Valid (1 warning(s))
  Title:        The Active Commodity Book
  Budget:       $8,000/mo
  Instruments:  9 core + 9 overlay
  Triggers:     9 (3 binary, 6 numeric)
  Overlays:     4
  Rules:        6
  --dry-run: no HTML generated.
```

### Morning Brief:
```
MORNING BRIEF — 2026-04-07
Generated: 21:31 UTC

IRAN/HORMUZ THESIS — MARCH 2026
[Phase 3: Amplification — APPROACHING]
  HOT NODES:
    em-stress: confluence 1.67
  APPROACHING: fert-shortage, planting-miss, food-spike
  DEADLINE: Planting Cycle Miss in 14 days
  ...

TRUMP TARIFF ESCALATION THESIS — MARCH 2026
[Phase 3: Amplification — STARTING]
  HOT NODES:
    earnings-compression: confluence 2.05
    consumer-confidence: confluence 1.95
    recession-risk: confluence 1.25
  ...

CROSS-BOOK ANALYSIS
  [HIGH] phase_alignment
  [HIGH] compound_recession
  [LOW] shared_market
```

### Test Suite:
```
223 passed in 15.98s
```

All 223 tests pass. No failures, no errors.

### Log Entry CLI:
```
  xop           TRD-XOP-HORMUZ  XOP   $188.18  (4 predicates)
  cf            TRD-CF-PLANTING  CF    $136.45  (3 predicates)
  spy-short     TRD-SH-RECESSION  SH    $15.50  (4 predicates)
```

### No backend or frontend server to start. All tools are CLI scripts that generate static output.
