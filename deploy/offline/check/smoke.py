"""The offline check's smoke test (scripts/offline-check.sh, design decision 16).

Runs from the backend image on the check's internal compose network, against
the frontend in demo mode and the stand-in model server. Each step prints
its name and whether it passed. The first failing step ends the test with
exit status 1; every step passing gives 0. Standard library only.
"""

import html.parser
import http.client
import json
import os
import re
import socket
import sys
import time
import uuid
from urllib.parse import urljoin, urlsplit

FRONTEND = os.environ.get("SMOKE_FRONTEND_URL", "http://frontend:3000")
BACKEND = os.environ.get("SMOKE_BACKEND_URL", "http://backend:8000")
STUB = os.environ.get("SMOKE_STUB_URL", "http://stub-provider:8080")
CHAT_MODEL = {"provider_id": "stub", "model": "stub-chat"}
OUTSIDE = (("example.com", 443), ("1.1.1.1", 80))
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
TIMEOUT = 30


class StepFailed(Exception):
    pass


class Response:
    def __init__(self, status: int, headers: http.client.HTTPMessage, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.body)


def request(method: str, url: str, *, cookie: str | None = None, body=None) -> Response:
    """One request, following no redirect."""
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=TIMEOUT)
    headers = {"Accept": "*/*"}
    data = None
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        connection.request(method, path, body=data, headers=headers)
        reply = connection.getresponse()
        return Response(reply.status, reply.headers, reply.read())
    except OSError as exc:
        raise StepFailed(f"{method} {url} could not be sent ({exc.__class__.__name__}: {exc})")
    finally:
        connection.close()


def expect(response: Response, status: int, what: str) -> Response:
    if response.status != status:
        raise StepFailed(f"{what} answered {response.status}, not {status}: {response.text[:300]}")
    return response


def sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        name, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def chat(cookie: str, message: str) -> list[tuple[str, dict]]:
    response = expect(
        request("POST", f"{FRONTEND}/api/chat", cookie=cookie, body={"message": message}),
        200,
        f"POST /api/chat ({message.split()[0]})",
    )
    events = sse_events(response.text)
    errors = [data for name, data in events if name == "error"]
    if errors:
        raise StepFailed(f"the chat stream ended with an error: {errors[0].get('error')}")
    if not events or events[-1][0] != "done":
        raise StepFailed(f"the chat stream did not end with done: {[name for name, _ in events]}")
    return events


class AssetParser(html.parser.HTMLParser):
    """The URLs a page loads: scripts, stylesheets, preloads, images, frames."""

    def __init__(self):
        super().__init__()
        self.loads: list[tuple[str, str]] = []
        self.stylesheets: list[str] = []
        self.inline_styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "img", "iframe", "source", "audio", "video", "embed") and attrs.get(
            "src"
        ):
            self.loads.append((tag, attrs["src"]))
        if tag in ("img", "source") and attrs.get("srcset"):
            for candidate in attrs["srcset"].split(","):
                if candidate.strip():
                    self.loads.append((tag, candidate.strip().split()[0]))
        if tag == "link" and attrs.get("href"):
            rel = (attrs.get("rel") or "").lower().split()
            if rel and set(rel) & {
                "stylesheet",
                "preload",
                "modulepreload",
                "icon",
                "manifest",
                "prefetch",
                "preconnect",
                "dns-prefetch",
                "apple-touch-icon",
            }:
                self.loads.append(("link " + " ".join(rel), attrs["href"]))
                if "stylesheet" in rel:
                    self.stylesheets.append(attrs["href"])
        if tag == "style":
            self._in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.inline_styles.append(data)


CSS_URL = re.compile(r"""url\(\s*['"]?([^'")\s]+)['"]?\s*\)|@import\s+['"]([^'"]+)['"]""")


def css_urls(css: str) -> list[str]:
    return [
        first or second
        for first, second in CSS_URL.findall(css)
        if not (first or "").startswith("data:")
    ]


def same_origin(url: str, base: str) -> bool:
    if url.startswith("data:"):
        return True
    absolute = urlsplit(urljoin(base, url))
    origin = urlsplit(FRONTEND)
    return (absolute.scheme, absolute.netloc) == (origin.scheme, origin.netloc)


def name_fonts(text: str, where: str) -> None:
    for host in FONT_HOSTS:
        if host in text:
            raise StepFailed(f"{where} references {host}")


# --- The steps ---------------------------------------------------------------


def step_network_is_internal(state: dict) -> str:
    reached = []
    for host, port in OUTSIDE:
        try:
            with socket.create_connection((host, port), timeout=5):
                reached.append(f"{host}:{port}")
        except OSError:
            pass
    if reached:
        raise StepFailed(f"the network is not internal: connected to {', '.join(reached)}")
    return "example.com:443 and 1.1.1.1:80 cannot be reached"


def step_demo_session(state: dict) -> str:
    response = request("GET", f"{FRONTEND}/")
    if response.status not in (302, 303, 307, 308):
        raise StepFailed(f"GET / answered {response.status}, not a redirect to /app")
    pair = None
    for header in response.headers.get_all("set-cookie") or []:
        name_value = header.split(";", 1)[0]
        if name_value.startswith("ff_demo="):
            pair = name_value
    if pair is None:
        raise StepFailed("GET / set no ff_demo cookie")
    # Copied by hand: the cookie is Secure, and this test speaks plain HTTP.
    state["cookie"] = pair
    return "GET / started a demo session"


def step_page_is_self_contained(state: dict) -> str:
    page_url = f"{FRONTEND}/app"
    page = expect(request("GET", page_url, cookie=state["cookie"]), 200, "GET /app")
    name_fonts(page.text, "/app")
    parser = AssetParser()
    parser.feed(page.text)
    outside = [url for _, url in parser.loads if not same_origin(url, page_url)]
    for css in parser.inline_styles:
        outside += [url for url in css_urls(css) if not same_origin(url, page_url)]
    if outside:
        raise StepFailed(f"/app loads from outside the app: {', '.join(sorted(set(outside)))}")
    if not parser.stylesheets:
        raise StepFailed("/app links no stylesheet")

    checked = 0
    for href in parser.stylesheets:
        sheet_url = urljoin(page_url, href)
        sheet = expect(request("GET", sheet_url, cookie=state["cookie"]), 200, f"GET {href}")
        name_fonts(sheet.text, href)
        for url in css_urls(sheet.text):
            if not same_origin(url, sheet_url):
                raise StepFailed(f"{href} loads {url} from outside the app")
            expect(request("GET", urljoin(sheet_url, url)), 200, f"GET {url} (from {href})")
            checked += 1
    for tag, url in parser.loads:
        if tag == "script":
            expect(request("GET", urljoin(page_url, url)), 200, f"GET {url}")
            checked += 1
    return (
        f"/app and its {len(parser.stylesheets)} stylesheet(s) use only the app's address; "
        f"{checked} scripts and fonts served"
    )


def step_choose_model(state: dict) -> str:
    body = {"models": [{**CHAT_MODEL, "is_default": True}], "temperature": None}
    saved = expect(
        request("PUT", f"{FRONTEND}/api/settings/models", cookie=state["cookie"], body=body),
        200,
        "PUT /api/settings/models",
    ).json()
    defaults = [entry for entry in saved["models"] if entry.get("is_default")]
    if [(entry["provider_id"], entry["model"]) for entry in defaults] != [("stub", "stub-chat")]:
        raise StepFailed(f"the default model is not stub-chat: {saved['models']}")
    return "stub-chat is the default model"


def step_push_and_confirm(state: dict) -> str:
    marker = uuid.uuid4().hex[:8]
    events = chat(state["cookie"], f"/push Offline check {marker}: water the plants on Friday")
    conversation = next((data for name, data in events if name == "conversation"), None)
    proposal = next((data for name, data in events if name == "proposal"), None)
    if conversation is None or proposal is None:
        raise StepFailed(f"/push gave no proposal: {[name for name, _ in events]}")
    part = proposal["parts"][0]
    confirmed = expect(
        request(
            "POST",
            f"{FRONTEND}/api/conversations/{conversation['id']}/proposals/{proposal['id']}/confirm",
            cookie=state["cookie"],
            body={
                "parts": [0],
                "title": part["title"],
                "summary": part["summary"],
                "tags": part["tags"],
                "category": part.get("category"),
            },
        ),
        200,
        "confirm",
    ).json()
    if not confirmed.get("saved") or not confirmed.get("thought_id"):
        raise StepFailed(f"confirm did not save a thought: {confirmed}")
    state["title"] = part["title"]
    state["marker"] = marker
    return f'/push proposed "{part["title"]}" and confirm saved it'


def step_pull(state: dict) -> str:
    events = chat(state["cookie"], f"/pull Offline check {state['marker']} plants")
    titles = [
        source.get("title")
        for name, data in events
        if name == "tool" and data.get("phase") == "end"
        for source in data.get("sources") or []
    ]
    if state["title"] not in titles:
        raise StepFailed(f'/pull did not find "{state["title"]}"; sources: {titles}')
    return f'/pull found "{state["title"]}"'


def step_stub_served(state: dict) -> str:
    served = expect(request("GET", f"{STUB}/_log"), 200, "GET /_log").json()["served"]
    needed = ["GET /v1/models", "POST /v1/chat/completions", "POST /v1/embeddings"]
    missing = [call for call in needed if call not in served]
    if missing:
        raise StepFailed(
            f"the stand-in never served {', '.join(missing)}; it served {sorted(set(served))}"
        )
    return f"the stand-in served the model list, chat, and embeddings ({len(served)} calls)"


STEPS = [
    ("an outside address cannot be reached", step_network_is_internal),
    ("a page starts a demo session", step_demo_session),
    ("the page references no outside host", step_page_is_self_contained),
    ("choose the stand-in model", step_choose_model),
    ("/push, then confirm the proposal", step_push_and_confirm),
    ("/pull finds the thought", step_pull),
    ("the stand-in served every call", step_stub_served),
]


def wait_until_started(limit_seconds: float = 180) -> str | None:
    """Wait for the backend (after its migrations), the frontend, and the stand-in."""
    pending = {
        "backend": f"{BACKEND}/health",
        "frontend": f"{FRONTEND}/favicon.ico",
        "stand-in": f"{STUB}/_log",
    }
    deadline = time.monotonic() + limit_seconds
    while pending and time.monotonic() < deadline:
        for name, url in list(pending.items()):
            try:
                if request("GET", url).status == 200:
                    del pending[name]
            except StepFailed:
                pass
        if pending:
            time.sleep(1)
    return ", ".join(pending) or None


def main() -> int:
    print("Waiting for the app to start...", flush=True)
    not_started = wait_until_started()
    if not_started:
        print(f"Offline check failed before step 1: {not_started} did not start.", flush=True)
        return 1
    state: dict = {}
    for number, (name, step) in enumerate(STEPS, start=1):
        try:
            detail = step(state)
        except StepFailed as exc:
            print(f"step {number} failed: {name}: {exc}", flush=True)
            print(f"Offline check failed at step {number} ({name}).", flush=True)
            return 1
        except Exception as exc:  # noqa: BLE001 - an unexpected answer shape fails the step too
            print(f"step {number} failed: {name}: {exc.__class__.__name__}: {exc}", flush=True)
            print(f"Offline check failed at step {number} ({name}).", flush=True)
            return 1
        print(f"step {number} passed: {name}: {detail}", flush=True)
    print(f"Offline check passed: all {len(STEPS)} steps.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
