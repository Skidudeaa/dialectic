"""Exercise actual newline JSON-RPC messages against the read-only server."""
import io
import json
import unittest

from custodian import mcp
from test_context import ContextFixture


class MCPTests(ContextFixture):
    @staticmethod
    def init(version="2025-06-18"):
        return [dict(jsonrpc="2.0", id=1, method="initialize",
                     params=dict(protocolVersion=version, capabilities={}, clientInfo=dict(name="test", version="1"))),
                dict(jsonrpc="2.0", method="notifications/initialized")]

    def exchange(self, messages):
        stream = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
        output = io.StringIO()
        mcp.serve(self.engine, stream, output)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_negotiation_and_read_only_tool_inventory(self):
        result = self.exchange(self.init("2099-01-01") + [dict(jsonrpc="2.0", id=2, method="tools/list")])
        self.assertEqual(len(result), 2)  # Initialized notification has no reply.
        self.assertEqual(result[0]["result"]["protocolVersion"], mcp.PROTOCOL_VERSION)
        tools = result[1]["result"]["tools"]
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))
        self.assertEqual({t["name"] for t in tools}, {"custodian_state", "custodian_attempt",
                                                     "custodian_history", "custodian_decisions", "custodian_repo_map"})

    def test_tool_and_resource_report_same_candidate(self):
        self.attempted("PASSED")
        result = self.exchange(self.init() + [
            dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(name="custodian_state", arguments={})),
            dict(jsonrpc="2.0", id=3, method="resources/read", params=dict(uri="custodian://state")),
        ])
        tool = json.loads(result[1]["result"]["content"][0]["text"])
        resource = json.loads(result[2]["result"]["contents"][0]["text"])
        self.assertEqual(tool["current_tree"], resource["current_tree"])
        self.assertEqual(tool["latest"]["id"], "attempt_fixture")
        self.assertTrue(tool["applicable"])

    def test_missing_attempt_is_tool_error_not_success(self):
        result = self.exchange(self.init() + [
            dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(name="custodian_attempt", arguments=dict(id="missing"))),
        ])
        self.assertTrue(result[-1]["result"]["isError"])

    def test_schema_rejects_unknown_keys_and_invalid_types(self):
        messages = self.init()
        for index, args in enumerate(({"limit": True}, {"execute": "rm"}, {"limit": 200}), 2):
            messages.append(dict(jsonrpc="2.0", id=index, method="tools/call",
                                 params=dict(name="custodian_history", arguments=args)))
        result = self.exchange(messages)
        self.assertTrue(all(r["error"]["code"] == -32602 for r in result[1:]))

    def test_requests_before_initialization_are_rejected(self):
        result = self.exchange([dict(jsonrpc="2.0", id=1, method="tools/list")])
        self.assertEqual(result[0]["error"]["code"], -32002)

    def test_invalid_request_id_does_not_produce_invalid_response(self):
        result = self.exchange([dict(jsonrpc="2.0", id={"invalid": True}, method="tools/list")])
        self.assertIsNone(result[0]["id"])
        self.assertEqual(result[0]["error"]["code"], -32600)

    def test_parse_error_and_oversized_input_stay_protocol_messages(self):
        output = io.StringIO()
        mcp.serve(self.engine, io.StringIO("{not json}\n" + "x" * (mcp.MAX_MESSAGE_BYTES + 1)), output)
        result = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["error"]["code"] for r in result], [-32700, -32600])


if __name__ == "__main__":
    unittest.main()
