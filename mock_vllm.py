"""Local mock of a vLLM OpenAI-compatible endpoint, for testing the client.

Returns a canned answer whose shape matches what the protocol asks for, with
a reasoning preamble in front of the JSON so the client's brace-tolerant
parser gets exercised the way it will in production.
"""
import json, re
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/health"):
            self._send(200, {"status": "ok"})
        elif self.path.endswith("/v1/models"):
            self._send(200, {"data": [{"id": "mock-model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        msgs = req.get("messages", [])
        user = ""
        for m in msgs:
            if m.get("role") == "user":
                user = m.get("content", "")
        # Decide the label from the code content so the test can assert on it.
        vuln = "strcpy" in user or "gets" in user
        decision = "vulnerable" if vuln else "not_vulnerable"
        content = (
            "Let me examine the code.\n\n"
            "```json\n"
            + json.dumps({
                "decision": decision,
                "evidence": "line 12: strcpy(buf, input)" if vuln else "no unsafe call found",
                "reason": "The code contains an unchecked copy." if vuln else "Nothing unsafe.",
                "insufficient_context": False,
            })
            + "\n```"
        )
        self._send(200, {
            "id": "mock-1",
            "object": "chat.completion",
            "model": req.get("model", "mock-model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 900,
                "completion_tokens": 60,
                "total_tokens": 960,
            },
        })


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
