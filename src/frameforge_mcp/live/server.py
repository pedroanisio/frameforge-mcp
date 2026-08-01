"""Dependency-free local web UI for FrameForge MCP live sessions.

The live server deliberately reuses the MCP feedback functions instead of
creating a second render path. Browser requests submit a prompt, SDK client
code, or YAML; the backend runs the existing validate/render loop and exposes
the generated YAML, diagnostics, and page artifacts over HTTP.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse
import webbrowser

from frameforge_mcp.server import read_session_resource, render_frameforge_yaml, run_sdk_code

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
MAX_REQUEST_BYTES = 1_000_000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8789


SAMPLE_SDK_CODE = """\
from frameforge_sdk import DocumentBuilder

doc = DocumentBuilder(title="Live FrameForge Session", profile="deck")
title = doc.define_text_style("title", font_family="sans", font_size=34, color="#0f172a")
body = doc.define_text_style("body", font_family="sans", font_size=18, color="#334155")
page = doc.page("p1", canvas={"size": [960, 540], "units": "px"}, reading_order=["h1", "body"])
layer = page.layer("main")
layer.rect([0, 0, 960, 540], fill="#f8fafc")
layer.rect([52, 54, 856, 432], fill="#ffffff", stroke_style={"stroke": "#cbd5e1", "stroke_width": 1}, radius=14)
page.text([86, 90, 780, 52], "Live FrameForge MCP", id="h1", style=title)
page.text(
    [88, 170, 760, 120],
    "Edit this SDK code, run it through the same MCP validation/render loop, and inspect the generated artifacts.",
    id="body",
    style=body,
)
doc.write(OUTPUT_YAML_PATH, fail_on_error=True)
"""


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FrameForge Live</title>
  <style>
    :root {
      --bg: #111318;
      --panel: #191d24;
      --panel-2: #202631;
      --ink: #f3f6fa;
      --muted: #9aa5b5;
      --line: #303846;
      --accent: #59c3a6;
      --accent-2: #f2b84b;
      --danger: #f06f6f;
      --paper: #f8fafc;
      --code: #0d1117;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, textarea, input, select { font: inherit; }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(360px, 42vw) minmax(420px, 1fr);
    }
    .left, .right { min-width: 0; }
    .left {
      padding: 18px;
      border-right: 1px solid var(--line);
      background: linear-gradient(180deg, #171b22, #111318);
    }
    .right {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) minmax(180px, 28vh);
      min-height: 100vh;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      background: #151922;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.1;
      font-weight: 650;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--accent-2);
      box-shadow: 0 0 0 3px rgba(242, 184, 75, .16);
    }
    .dot.ok {
      background: var(--accent);
      box-shadow: 0 0 0 3px rgba(89, 195, 166, .14);
    }
    .controls {
      display: grid;
      grid-template-columns: 1fr 120px;
      gap: 10px;
      margin-bottom: 12px;
    }
    .tabs {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 6px;
      padding: 5px;
      background: #11161d;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .tab, .button {
      border: 1px solid transparent;
      border-radius: 7px;
      color: var(--ink);
      background: transparent;
      min-height: 36px;
      cursor: pointer;
    }
    .tab.active {
      background: var(--panel-2);
      border-color: #3d4858;
    }
    .button {
      background: var(--accent);
      color: #06110e;
      font-weight: 700;
    }
    .button.secondary {
      background: var(--panel-2);
      color: var(--ink);
      border-color: var(--line);
    }
    textarea {
      width: 100%;
      height: calc(100vh - 188px);
      min-height: 360px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--code);
      color: #dbe7f3;
      padding: 14px;
      line-height: 1.45;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      outline: none;
    }
    textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(89, 195, 166, .12);
    }
    .preview {
      min-height: 0;
      padding: 18px;
      background: #0f1217;
    }
    .frame {
      width: 100%;
      height: 100%;
      min-height: 420px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
      overflow: hidden;
      display: grid;
      place-items: center;
    }
    .frame iframe {
      width: 100%;
      height: 100%;
      border: 0;
      background: var(--paper);
    }
    .empty {
      color: #667085;
      font-size: 14px;
    }
    .bottom {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, .55fr);
      border-top: 1px solid var(--line);
      background: #151922;
      min-height: 0;
    }
    .pane {
      min-width: 0;
      min-height: 0;
      padding: 14px 16px;
      border-right: 1px solid var(--line);
      overflow: auto;
    }
    .pane:last-child { border-right: 0; }
    .pane h2 {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #cbd5e1;
      font-size: 12px;
      line-height: 1.4;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .timeline {
      display: grid;
      gap: 8px;
      font-size: 12px;
      color: #cbd5e1;
    }
    .event {
      display: grid;
      grid-template-columns: 84px minmax(0, 1fr);
      gap: 8px;
      padding-bottom: 8px;
      border-bottom: 1px solid #252c37;
    }
    .event time { color: var(--muted); }
    .error { color: var(--danger); }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      .left { border-right: 0; border-bottom: 1px solid var(--line); }
      textarea { height: 360px; }
      .right { min-height: 720px; }
      .bottom { grid-template-columns: 1fr; }
      .pane { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="left">
      <div class="controls">
        <div class="tabs" role="tablist" aria-label="Run mode">
          <button class="tab active" data-mode="prompt">Prompt</button>
          <button class="tab" data-mode="sdk">SDK</button>
          <button class="tab" data-mode="yaml">YAML</button>
          <button class="tab" data-mode="sample">Sample</button>
        </div>
        <button id="run" class="button">Run</button>
      </div>
      <textarea id="input" spellcheck="false"></textarea>
    </section>
    <section class="right">
      <header>
        <h1>FrameForge Live Session</h1>
        <div class="status"><span id="dot" class="dot"></span><span id="status">starting</span></div>
      </header>
      <section class="preview">
        <div class="frame" id="frame"><div class="empty">No render yet</div></div>
      </section>
      <section class="bottom">
        <div class="pane">
          <h2>Diagnostics</h2>
          <pre id="diagnostics">{}</pre>
        </div>
        <div class="pane">
          <h2>Timeline</h2>
          <div id="timeline" class="timeline"></div>
        </div>
      </section>
    </section>
  </main>
  <script>
    const initialPrompt = "Create a one-page FrameForge status card for a live MCP feedback loop.";
    const sampleCode = __SAMPLE_CODE__;
    const sampleYaml = `dsl: FrameForge
version: "2.2.0"
profile: deck
title: Live YAML Render
pages:
  - mode: page
    id: p1
    canvas: {size: [640, 360], units: px}
    reading_order: [title]
    layers:
      - id: main
        objects:
          - {type: rect, box: [0, 0, 640, 360], fill: "#f8fafc"}
          - {type: text, id: title, box: [48, 62, 520, 56], text: "Rendered from YAML", style: {font_size: 30, color: "#0f172a"}}
`;
    const state = { sessionId: null, mode: "prompt" };
    const input = document.getElementById("input");
    const statusEl = document.getElementById("status");
    const dot = document.getElementById("dot");
    const frame = document.getElementById("frame");
    const diagnostics = document.getElementById("diagnostics");
    const timeline = document.getElementById("timeline");

    function setStatus(text, ok) {
      statusEl.textContent = text;
      dot.classList.toggle("ok", !!ok);
    }

    function setMode(mode) {
      state.mode = mode;
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
      if (mode === "prompt") input.value = initialPrompt;
      if (mode === "sdk") input.value = sampleCode;
      if (mode === "yaml") input.value = sampleYaml;
      if (mode === "sample") input.value = sampleCode;
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        headers: {"content-type": "application/json", ...(options.headers || {})}
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }

    async function createSession() {
      const data = await api("/api/sessions", {method: "POST", body: "{}"});
      state.sessionId = data.session_id;
      renderSession(data);
      setStatus(`session ${state.sessionId}`, true);
    }

    function renderSession(session) {
      diagnostics.textContent = JSON.stringify(session.last_result || {}, null, 2);
      timeline.innerHTML = "";
      (session.events || []).slice().reverse().forEach((event) => {
        const item = document.createElement("div");
        item.className = "event";
        item.innerHTML = `<time>${new Date(event.timestamp).toLocaleTimeString()}</time><span>${event.type}</span>`;
        timeline.appendChild(item);
      });
      const result = session.last_result || {};
      const render = (result.renders || []).find((item) => item.mimeType === "image/svg+xml");
      if (render && render.web_url) {
        frame.innerHTML = "";
        const iframe = document.createElement("iframe");
        iframe.src = render.web_url;
        iframe.title = "Rendered FrameForge page";
        frame.appendChild(iframe);
      }
    }

    async function run() {
      if (!state.sessionId) await createSession();
      setStatus("running", false);
      const mode = state.mode === "sample" ? "sdk" : state.mode;
      try {
        const data = await api(`/api/sessions/${state.sessionId}/runs`, {
          method: "POST",
          body: JSON.stringify({mode, content: input.value, max_pages: 3, raster_png: false})
        });
        renderSession(data);
        setStatus(data.last_result && data.last_result.ok ? "rendered" : "needs attention", !!(data.last_result && data.last_result.ok));
      } catch (err) {
        diagnostics.textContent = String(err.stack || err);
        setStatus("error", false);
      }
    }

    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));
    document.getElementById("run").addEventListener("click", run);
    setMode("prompt");
    createSession().catch((err) => setStatus(err.message, false));
  </script>
</body>
</html>
"""


class LiveSessionStore:
    """Session manager that drives the existing FrameForge MCP render loop."""

    def __init__(self, session_root: str | Path | None = None) -> None:
        root = Path(session_root) if session_root is not None else Path(tempfile.gettempdir()) / "frameforge-live"
        self.session_root = root.expanduser().resolve()
        self.session_root.mkdir(parents=True, exist_ok=True)

    def create_session(self, session_id: str | None = None) -> dict[str, Any]:
        sid = self._session_id(session_id)
        session_dir = self.session_root / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        if not self._metadata_path(sid).exists():
            session = {
                "session_id": sid,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "events": [],
                "last_result": None,
            }
            self._append_event(session, "session_created", {"session_id": sid})
            self._write_session(session)
        return self.get_session(sid)

    def get_session(self, session_id: str) -> dict[str, Any]:
        sid = self._session_id(session_id)
        path = self._metadata_path(sid)
        if not path.exists():
            raise FileNotFoundError(f"unknown live session: {sid}")
        return json.loads(path.read_text(encoding="utf-8"))

    def run(self, session_id: str, mode: str, content: str, *, max_pages: int = 3, raster_png: bool = False) -> dict[str, Any]:
        sid = self._session_id(session_id)
        session = self.get_session(sid)
        mode = _normalize_mode(mode)
        max_pages = _bounded_int(max_pages, minimum=1, maximum=20)
        self._append_event(session, "run_started", {"mode": mode})
        self._write_session(session)

        try:
            if mode == "prompt":
                code = build_prompt_code(content)
                result = run_sdk_code(
                    code,
                    session_id=sid,
                    session_root=self.session_root,
                    max_pages=max_pages,
                    raster_png=raster_png,
                )
                result["live_mode"] = "prompt"
                result["generated_sdk_code"] = code
            elif mode == "sdk":
                result = run_sdk_code(
                    content,
                    session_id=sid,
                    session_root=self.session_root,
                    max_pages=max_pages,
                    raster_png=raster_png,
                )
                result["live_mode"] = "sdk"
            elif mode == "yaml":
                result = render_frameforge_yaml(
                    content,
                    session_id=sid,
                    session_root=self.session_root,
                    max_pages=max_pages,
                    raster_png=raster_png,
                )
                result["live_mode"] = "yaml"
            else:
                raise ValueError(f"unsupported mode: {mode}")
        except Exception as exc:  # noqa: BLE001
            result = {
                "ok": False,
                "session_id": sid,
                "live_mode": mode,
                "error": f"{type(exc).__name__}: {exc}",
                "validation": {"ok": False, "issues": [{"severity": "error", "message": str(exc)}]},
                "renders": [],
                "resources": [],
            }

        result = _with_web_urls(result)
        session = self.get_session(sid)
        session["last_result"] = result
        session["updated_at"] = _utc_now()
        self._append_event(
            session,
            "run_completed",
            {"mode": mode, "ok": bool(result.get("ok")), "render_count": len(result.get("renders", []))},
        )
        self._write_session(session)
        return self.get_session(sid)

    def read_resource(self, session_id: str, artifact: str) -> tuple[str, bytes]:
        sid = self._session_id(session_id)
        uri = f"frameforge://session/{sid}/{artifact.strip('/')}"
        resource = read_session_resource(uri, session_root=self.session_root)
        mime = resource["mimeType"]
        if "blob" in resource:
            return mime, base64.b64decode(resource["blob"])
        return mime, resource.get("text", "").encode("utf-8")

    def _metadata_path(self, session_id: str) -> Path:
        return self.session_root / session_id / "live-session.json"

    def _write_session(self, session: dict[str, Any]) -> None:
        path = self._metadata_path(str(session["session_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _append_event(self, session: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        session.setdefault("events", []).append({"timestamp": _utc_now(), "type": event_type, "payload": payload})
        session["updated_at"] = _utc_now()

    def _session_id(self, session_id: str | None) -> str:
        sid = session_id or f"live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        if not SESSION_ID_RE.fullmatch(sid):
            raise ValueError("session_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
        return sid


class LiveRequestHandler(BaseHTTPRequestHandler):
    """HTTP API and static UI handler for the live-session app."""

    server_version = "FrameForgeLive/1.0"

    def __init__(self, *args: Any, store: LiveSessionStore, **kwargs: Any) -> None:
        self.store = store
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self._send_text("text/html; charset=utf-8", html_index())
                return
            if path == "/api/health":
                self._send_json({"ok": True, "service": "frameforge-live", "session_root": str(self.store.session_root)})
                return
            if path.startswith("/api/sessions/") and path.endswith("/events"):
                session_id = path.split("/")[3]
                self._send_events(self.store.get_session(session_id).get("events", []))
                return
            resource_prefix = "/api/sessions/"
            if path.startswith(resource_prefix) and "/resources/" in path:
                parts = path[len(resource_prefix) :].split("/resources/", 1)
                session_id = unquote(parts[0])
                artifact = unquote(parts[1])
                mime, data = self.store.read_resource(session_id, artifact)
                self._send_bytes(mime, data)
                return
            if path.startswith("/api/sessions/"):
                session_id = unquote(path.rsplit("/", 1)[-1])
                self._send_json(self.store.get_session(session_id))
                return
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
        except Exception as exc:  # noqa: BLE001
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json()
            if path == "/api/sessions":
                self._send_json(self.store.create_session(payload.get("session_id")))
                return
            if path.startswith("/api/sessions/") and path.endswith("/runs"):
                session_id = path.split("/")[3]
                session = self.store.run(
                    session_id,
                    str(payload.get("mode", "prompt")),
                    str(payload.get("content", "")),
                    max_pages=int(payload.get("max_pages", 3)),
                    raster_png=bool(payload.get("raster_png", False)),
                )
                self._send_json(session)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
        except Exception as exc:  # noqa: BLE001
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or "0")
        if length > MAX_REQUEST_BYTES:
            raise ValueError(f"request exceeds {MAX_REQUEST_BYTES} bytes")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes("application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"), status)

    def _send_text(self, mime: str, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(mime, text.encode("utf-8"), status)

    def _send_bytes(self, mime: str, data: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(int(status))
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_events(self, events: list[dict[str, Any]]) -> None:
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
        self._send_text("text/event-stream; charset=utf-8", body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status)


def html_index() -> str:
    """Return the live app shell with the sample SDK code embedded."""
    return INDEX_HTML.replace("__SAMPLE_CODE__", json.dumps(SAMPLE_SDK_CODE))


def build_prompt_code(prompt: str) -> str:
    """Build a conservative SDK draft from a prompt for the live feedback loop."""
    text = " ".join(str(prompt or "Untitled FrameForge live session").split())[:900]
    return f"""\
from frameforge_sdk import DocumentBuilder

prompt = {text!r}
doc = DocumentBuilder(title="Agentic FrameForge Draft", profile="deck")
title = doc.define_text_style("title", font_family="sans", font_size=38, color="#0f172a")
body = doc.define_text_style("body", font_family="sans", font_size=20, color="#334155", line_height=1.25, wrap=True)
label = doc.define_text_style("label", font_family="sans", font_size=14, color="#64748b")
page = doc.page("p1", canvas={{"size": [960, 540], "units": "px"}}, reading_order=["kicker", "title", "prompt"])
layer = page.layer("main")
layer.rect([0, 0, 960, 540], fill="#eef2f7")
layer.rect([56, 48, 848, 444], fill="#ffffff", stroke_style={{"stroke": "#cbd5e1", "stroke_width": 1}}, radius=18)
page.text([88, 86, 360, 24], "AGENTIC MCP DRAFT", id="kicker", style=label)
page.text([86, 126, 720, 54], "FrameForge live session", id="title", style=title)
page.text([88, 210, 760, 128], prompt, id="prompt", style=body)
layer.rect([88, 388, 210, 44], fill="#59c3a6", radius=8)
page.text([110, 401, 170, 18], "validated render loop", id="status", style={{"font_size": 15, "color": "#06251d"}})
doc.write(OUTPUT_YAML_PATH, fail_on_error=True)
"""


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    session_root: str | Path | None = None,
    open_browser: bool = False,
) -> ThreadingHTTPServer:
    """Start the live web server and block until interrupted."""
    store = LiveSessionStore(session_root=session_root)

    class Handler(LiveRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, store=store, **kwargs)

    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    url = f"http://{host}:{httpd.server_port}/"
    print(f"FrameForge live session: {url}", flush=True)
    print(f"Session artifacts: {store.session_root}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return httpd


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the FrameForge live-session web UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--session-root", default=None)
    parser.add_argument("--open", action="store_true", help="open the UI in the default browser")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, session_root=args.session_root, open_browser=args.open)


def _with_web_urls(result: dict[str, Any]) -> dict[str, Any]:
    sid = str(result.get("session_id", "session"))
    copied = json.loads(json.dumps(result, ensure_ascii=False, default=str))
    for render in copied.get("renders", []):
        uri = str(render.get("uri", ""))
        artifact = uri.split(f"frameforge://session/{sid}/", 1)[-1]
        render["web_url"] = f"/api/sessions/{sid}/resources/{artifact}"
    for resource in copied.get("resources", []):
        uri = str(resource.get("uri", ""))
        if uri.startswith(f"frameforge://session/{sid}/"):
            artifact = uri.split(f"frameforge://session/{sid}/", 1)[-1]
            resource["web_url"] = f"/api/sessions/{sid}/resources/{artifact}"
    return copied


def _normalize_mode(mode: str) -> str:
    value = str(mode or "prompt").strip().lower()
    aliases = {"code": "sdk", "sdk_code": "sdk", "frameforge": "yaml"}
    value = aliases.get(value, value)
    if value not in {"prompt", "sdk", "yaml"}:
        raise ValueError("mode must be prompt, sdk, or yaml")
    return value


def _bounded_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
