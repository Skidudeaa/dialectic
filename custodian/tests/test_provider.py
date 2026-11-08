"""Real loopback HTTP contract tests; no paid network calls or real credentials."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from custodian.provider import BudgetExceeded, Provider, ProviderCancelled, ProviderError, validate_edits


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.requests = []
        self.count = 10
        self.reply = dict(id="message-test", usage=dict(input_tokens=10, output_tokens=20),
                          stop_reason="end_turn", content=[dict(type="text", text=json.dumps({
                              "edits": [{"path": "app.py", "expected_sha256": hashlib.sha256(b"old").hexdigest(), "content": "new"}],
                              "rationale": "Fix the observed failure"}))])
        self.http_status = 200
        self.delay = 0
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                parent.requests.append((self.path, body, dict(self.headers)))
                if self.path.endswith("/count_tokens"):
                    response, code = {"input_tokens": parent.count}, 200
                else:
                    time.sleep(parent.delay)
                    response, code = parent.reply, parent.http_status
                raw = json.dumps(response).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("request-id", "request-test")
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except BrokenPipeError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = dict(model="test-model", input_usd_per_million="1", output_usd_per_million="3",
                           daily_budget_usd="5", max_input_tokens=100, max_output_tokens=50,
                           endpoint=f"http://127.0.0.1:{self.server.server_port}/v1/messages",
                           allow_local_test_endpoint=True, api_key_env="CUSTODIAN_TEST_KEY", timeout_seconds=2)
        self.env = patch.dict(os.environ, CUSTODIAN_TEST_KEY="test-only-not-a-secret")
        self.env.start()
        self.addCleanup(self.env.stop)

    def provider(self, **overrides):
        return Provider(self.state, dict(self.config, **overrides))

    def test_complete_proposal_has_bounded_request_and_durable_accounting(self):
        provider = self.provider()
        result = provider.propose({"files": {"app.py": "old"}, "failure": "observed failure"})
        self.assertEqual(result["edits"][0]["content"], "new")
        self.assertEqual(result["request_id"], "request-test")
        self.assertEqual(result["cost_usd"], "0.00007")
        self.assertEqual(result["reserved_usd"], "0.00025")
        self.assertEqual([r[0] for r in self.requests], ["/v1/messages/count_tokens", "/v1/messages"])
        self.assertEqual(self.requests[1][1]["max_tokens"], 50)
        self.assertNotIn("tools", self.requests[1][1])
        self.assertEqual(self.requests[1][2]["Authorization"], "Bearer test-only-not-a-secret")
        self.assertEqual(self.provider().budget_status()["accounted_usd"], "0.00007")
        self.assertNotIn(b"test-only-not-a-secret", (self.state / "provider.sqlite3").read_bytes())

    def test_count_exceeding_allowance_prevents_paid_dispatch(self):
        self.count = 101
        with self.assertRaises(ProviderError):
            self.provider().propose({})
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.provider().budget_status()["accounted_usd"], "0")

    def test_unaffordable_reservation_prevents_paid_dispatch(self):
        provider = self.provider(daily_budget_usd="0.000249")
        with self.assertRaises(BudgetExceeded):
            provider.propose({})
        self.assertEqual(len(self.requests), 1)

    def test_uncertain_response_retains_full_reservation_across_restart(self):
        self.http_status = 500
        provider = self.provider(daily_budget_usd="0.00025")
        with self.assertRaises(ProviderError):
            provider.propose({})
        recovered = self.provider(daily_budget_usd="0.00025")
        self.assertEqual(recovered.budget_status()["accounted_usd"], "0.00025")
        self.assertEqual(recovered.budget_status()["uncertain_reservations"], 1)
        with self.assertRaises(BudgetExceeded):
            recovered.propose({})
        self.assertEqual(sum(path == "/v1/messages" for path, _, _ in self.requests), 1)

    def test_missing_usage_never_releases_reservation(self):
        del self.reply["usage"]
        provider = self.provider()
        with self.assertRaises(ProviderError):
            provider.propose({})
        self.assertEqual(provider.budget_status()["uncertain_reservations"], 1)

    def test_observed_bound_breach_disables_subsequent_paid_calls(self):
        self.reply["usage"]["input_tokens"] = 101
        provider = self.provider()
        with self.assertRaises(BudgetExceeded):
            provider.propose({})
        self.assertTrue(self.provider().budget_status()["halted"])
        with self.assertRaises(BudgetExceeded):
            self.provider().propose({})
        self.assertEqual(sum(path == "/v1/messages" for path, _, _ in self.requests), 1)

    def test_concurrent_reservations_cannot_double_spend(self):
        providers = [self.provider(daily_budget_usd="0.00025") for _ in range(8)]
        barrier = threading.Barrier(len(providers))

        def reserve(provider):
            barrier.wait()
            try:
                provider._reserve("hash", 10)
                return True
            except BudgetExceeded:
                return False

        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            results = list(pool.map(reserve, providers))
        self.assertEqual(sum(results), 1)
        self.assertEqual(providers[0].budget_status()["accounted_usd"], "0.00025")

    def test_cancelled_delivery_returns_promptly_without_retry_or_refund(self):
        self.delay = 0.5
        provider = self.provider()
        deadline = time.monotonic() + 0.1
        with self.assertRaises(ProviderCancelled):
            provider.propose({}, cancel=lambda: time.monotonic() >= deadline)
        self.assertEqual(provider.budget_status()["uncertain_reservations"], 1)
        self.assertEqual(sum(path == "/v1/messages" for path, _, _ in self.requests), 1)

    def test_invalid_model_output_still_charges_observed_usage(self):
        self.reply["content"][0]["text"] = '{"command": ["sh", "-c", "echo bad"]}'
        provider = self.provider()
        with self.assertRaises(ProviderError):
            provider.propose({})
        self.assertEqual(provider.budget_status()["accounted_usd"], "0.00007")
        self.assertEqual(provider.budget_status()["uncertain_reservations"], 0)

    def test_truncated_model_output_is_not_an_edit(self):
        self.reply["stop_reason"] = "max_tokens"
        with self.assertRaises(ProviderError):
            self.provider().propose({})

    def test_credentials_cannot_be_sent_to_arbitrary_endpoint(self):
        with self.assertRaises(ProviderError):
            self.provider(endpoint="https://example.invalid/v1/messages")

    def test_context_limit_prevents_network_work(self):
        with self.assertRaises(ProviderError):
            self.provider(max_input_bytes=2).propose({"large": "input"})
        self.assertEqual(self.requests, [])


class EditValidationTests(unittest.TestCase):
    def test_path_traversal_git_paths_duplicates_and_unknown_fields_are_rejected(self):
        for path in ("../escape", "/absolute", "a/../../escape", "a/.git/config", "a//b", "a\\b", "./a"):
            with self.subTest(path=path), self.assertRaises(ProviderError):
                validate_edits([dict(path=path, expected_sha256=None, content="x")])
        edit = dict(path="ok.py", expected_sha256=None, content="x")
        with self.assertRaises(ProviderError):
            validate_edits([edit, edit])
        with self.assertRaises(ProviderError):
            validate_edits([dict(edit, command="shell")])

    def test_original_hash_and_replacement_limits_are_enforced(self):
        with self.assertRaises(ProviderError):
            validate_edits([dict(path="ok.py", content="x")])
        with self.assertRaises(ProviderError):
            validate_edits([dict(path="ok.py", expected_sha256=None, delete=True)])
        with self.assertRaises(ProviderError):
            validate_edits([dict(path="ok.py", expected_sha256=None, content="xxxxx")], max_bytes=4)
        self.assertEqual(validate_edits([]), [])


if __name__ == "__main__":
    unittest.main()
