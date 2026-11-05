"""The offline check's stand-in model server (scripts/offline-check.sh).

An OpenAI-compatible server with the standard library only, run from the
backend image on the check's internal network. It serves:

- GET /v1/models: one chat model and one embedding model.
- POST /v1/embeddings: deterministic vectors, one count per hashed word, so
  texts that share words are close.
- POST /v1/chat/completions (streamed): when a tool result is present, a
  short text answer; when a function is forced, a call to it with arguments
  valid for the backend's tool schemas; otherwise a text answer. Each stream
  ends with a usage chunk with no choices, then [DONE].
- GET /_log: the method and path of every request it served, for the smoke
  test's last step.
"""

import hashlib
import json
import math
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
CHAT_MODEL = "stub-chat"
EMBED_MODEL = "stub-embed"
DIMENSIONS = 64
COMMAND = re.compile(r"^\s*/(push|pull|explore)\s+", re.IGNORECASE)

served: list[str] = []
served_lock = threading.Lock()


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"\w+", text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % DIMENSIONS] += 1.0
    if not any(vector):
        vector[0] = 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return COMMAND.sub("", text_of(message.get("content"))).strip()
    return ""


def category_for(tools: list[dict]) -> str:
    """A category the propose tool's schema accepts: note when offered."""
    for tool in tools:
        function = tool.get("function", {})
        if function.get("name") != "propose_thought":
            continue
        part = function["parameters"]["properties"]["thoughts"]["items"]
        offered = part["properties"]["category"].get("enum") or []
        return "note" if "note" in offered else (offered[0] if offered else "note")
    return "note"


def tool_arguments(name: str, text: str, tools: list[dict]) -> dict:
    if name == "propose_thought":
        title = " ".join(text.split()[:8]) or "Offline check"
        return {
            "thoughts": [
                {
                    "title": title,
                    "summary": text or title,
                    "tags": ["offline-check"],
                    "category": category_for(tools),
                }
            ]
        }
    if name == "search_thoughts":
        return {"query": text or "offline check"}
    return {}


def chunk(delta: dict | None, finish: str | None = None, usage: dict | None = None) -> dict:
    body = {"id": "stub", "object": "chat.completion.chunk", "created": 0, "model": CHAT_MODEL}
    body["choices"] = (
        [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
    )
    if usage is not None:
        body["usage"] = usage
    return body


def chat_chunks(body: dict) -> list[dict]:
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    choice = body.get("tool_choice")
    forced = choice.get("function", {}).get("name") if isinstance(choice, dict) else None
    text = last_user_text(messages)
    usage = {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}

    if messages and messages[-1].get("role") == "tool":
        answer = "Done. This answer came from the offline check's stand-in model."
        return [
            chunk({"role": "assistant", "content": answer}),
            chunk({}, "stop"),
            chunk(None, usage=usage),
        ]
    if forced:
        arguments = json.dumps(tool_arguments(forced, text, tools))
        call = {
            "index": 0,
            "id": "call_stub_1",
            "type": "function",
            "function": {"name": forced, "arguments": arguments},
        }
        return [
            chunk({"role": "assistant", "tool_calls": [call]}),
            chunk({}, "tool_calls"),
            chunk(None, usage=usage),
        ]
    return [
        chunk({"role": "assistant", "content": f"Stand-in answer to: {text[:80]}"}),
        chunk({}, "stop"),
        chunk(None, usage=usage),
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        sys.stderr.write("stub-provider: " + (format % args) + "\n")

    def _note(self) -> str:
        path = self.path.split("?", 1)[0]
        if path != "/_log":
            with served_lock:
                served.append(f"{self.command} {path}")
        return path

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        path = self._note()
        if path == "/_log":
            with served_lock:
                return self._json(200, {"served": list(served)})
        if path.rstrip("/") == "/v1/models":
            return self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": model, "object": "model", "created": 0, "owned_by": "offline-check"}
                        for model in (CHAT_MODEL, EMBED_MODEL)
                    ],
                },
            )
        return self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        path = self._note().rstrip("/")
        body = self._body()
        if path == "/v1/embeddings":
            given = body.get("input")
            texts = given if isinstance(given, list) else [given]
            data = [
                {"object": "embedding", "index": index, "embedding": embed(str(text))}
                for index, text in enumerate(texts)
            ]
            tokens = sum(len(str(text).split()) for text in texts)
            return self._json(
                200,
                {
                    "object": "list",
                    "model": body.get("model", EMBED_MODEL),
                    "data": data,
                    "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                },
            )
        if path == "/v1/chat/completions":
            chunks = chat_chunks(body)
            if not body.get("stream"):
                return self._json(400, {"error": {"message": "the stand-in only streams"}})
            payload = (
                b"".join(f"data: {json.dumps(item)}\n\n".encode() for item in chunks)
                + b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return self._json(404, {"error": {"message": "not found"}})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"stub-provider: listening on port {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
