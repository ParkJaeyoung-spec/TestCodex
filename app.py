"""Loopback server for the local technical document workbench."""
import argparse
import io
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"
TRIGGER = "https://api.chatgpt.com/v1/workspace_agents/"
AGENT_ID = re.compile(r"agtch_[A-Za-z0-9_-]{1,120}")
COOKIE = "techdocs_session"
TTL = 4 * 60 * 60
MAX_FILE = 20 * 1024 * 1024
MAX_INPUT = 100_000
ASSETS = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          "/app.css": ("app.css", "text/css"), "/app.js": ("app.js", "text/javascript")}
ERRORS = {
    400: "Agent 입력 또는 API 채널 설정을 확인하세요.",
    401: "액세스 토큰이 유효하지 않거나 만료되었습니다.",
    403: "이 토큰에 해당 Agent 실행 권한이 없습니다.",
    404: "게시된 Agent의 API Trigger를 찾을 수 없습니다.",
    409: "게시 상태와 API 채널 설정을 확인하세요.",
    429: "Agent 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.",
}


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def trigger_id(value):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(TRIGGER) and value.endswith("/trigger"):
            value = value.removeprefix(TRIGGER).removesuffix("/trigger")
        if AGENT_ID.fullmatch(value):
            return value
    raise RequestError(400, "API Trigger URL 또는 agtch_로 시작하는 ID를 입력하세요.")


def run_agent(session, message, request_id):
    agent_id, token, _, _ = session
    request = urllib.request.Request(
        TRIGGER + agent_id + "/trigger",
        data=json.dumps({"input": message}, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "Idempotency-Key": request_id},
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=35) as response:
            if response.status != 202:
                raise ValueError
            payload = json.load(response)
        value = payload.get("conversation_url") if isinstance(payload, dict) else None
        if isinstance(value, str):
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme == "https" and parsed.netloc == "chatgpt.com" and parsed.path.startswith("/c/"):
                return value
        return None
    except urllib.error.HTTPError as error:
        raise RequestError(error.code if error.code in ERRORS else 502,
                           ERRORS.get(error.code, "Agent 서버에서 요청을 처리하지 못했습니다.")) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise RequestError(502, "Agent 응답을 확인하지 못했습니다. 네트워크 연결을 확인하세요.") from None


def read_document(content, kind):
    try:
        if kind == "pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                raise RequestError(422, "PDF 추출에는 pypdf 설치가 필요합니다.") from None
            pdf = PdfReader(io.BytesIO(content))
            if pdf.is_encrypted:
                raise RequestError(422, "암호화된 PDF입니다. 열 수 있는 사본을 사용하세요.")
            return "\n\n".join(f"[{index}페이지]\n{text}" for index, page in enumerate(pdf.pages, 1)
                               if (text := (page.extract_text() or "").strip()))
        if kind == "pptx":
            with zipfile.ZipFile(io.BytesIO(content)) as deck:
                slides = []
                for entry in deck.infolist():
                    match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", entry.filename)
                    if match:
                        slides.append((int(match[1]), entry))
                if sum(entry.file_size for _, entry in slides) > MAX_FILE:
                    raise RequestError(413, "슬라이드 텍스트 구조가 너무 큽니다.")
                sections = []
                for number, entry in sorted(slides, key=lambda slide: slide[0]):
                    root = ET.fromstring(deck.read(entry))
                    text = "\n".join("".join(part.itertext()) for part in
                                     root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"))
                    if text.strip():
                        sections.append(f"[슬라이드 {number}]\n{text}")
                return "\n\n".join(sections)
    except RequestError:
        raise
    except Exception:
        raise RequestError(422, "문서의 텍스트를 읽지 못했습니다.") from None
    raise RequestError(400, "PDF와 PPTX의 텍스트 추출을 지원합니다.")


class Server(ThreadingHTTPServer):
    def __init__(self, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.sessions = {}
        self.lock = threading.Lock()

    def service_actions(self):
        now = time.monotonic()
        with self.lock:
            for key in [key for key, session in self.sessions.items() if session[2] <= now]:
                self.sessions.pop(key, None)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def verify_origin(self, post=False):
        if "http://" + self.headers.get("Host", "") != self.server.origin or (
                post and self.headers.get("Origin") != self.server.origin):
            raise RequestError(403, "워크벤치의 로컬 주소에서 요청하세요.")

    def send(self, status, body, mime, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        if cookie is not None:
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/api/; HttpOnly; SameSite=Strict; Max-Age={TTL if cookie else 0}")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, data, cookie=None):
        self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json", cookie)

    def session_key(self):
        cookie = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
        return cookie.value if cookie else ""

    def read_body(self, max_size):
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise RequestError(400, "요청 크기를 확인할 수 없습니다.") from None
        if not 0 < size <= max_size:
            raise RequestError(413, "요청 크기 한도를 초과했습니다.")
        data = self.rfile.read(size)
        if len(data) != size:
            raise RequestError(400, "요청 본문이 불완전합니다.")
        return data

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "JSON 요청만 지원합니다.")
        try:
            result = json.loads(self.read_body(8 * MAX_INPUT))
        except ValueError:
            raise RequestError(400, "요청 형식을 확인하세요.") from None
        if not isinstance(result, dict):
            raise RequestError(400, "요청 형식을 확인하세요.")
        return result

    def do_GET(self):
        try:
            self.verify_origin()
            path = urllib.parse.urlsplit(self.path).path
            if path in ASSETS:
                file, mime = ASSETS[path]
                return self.send(200, (DIST / file).read_bytes(), mime)
            if path == "/api/session":
                with self.server.lock:
                    session = self.server.sessions.get(self.session_key())
                active = bool(session and session[2] > time.monotonic())
                return self.send_json(200, {"configured": active, "verified": active and session[3]})
            raise RequestError(404, "페이지를 찾을 수 없습니다.")
        except RequestError as error:
            self.send_json(error.status, {"error":str(error)})

    def do_POST(self):
        try:
            self.verify_origin(post=True)
            route = urllib.parse.urlsplit(self.path)
            if route.path == "/api/extract":
                if self.headers.get_content_type() != "application/octet-stream":
                    raise RequestError(415, "문서 파일을 보내세요.")
                kind = urllib.parse.parse_qs(route.query).get("format", [""])[0]
                return self.send_json(200, {"text":read_document(self.read_body(MAX_FILE), kind)})
            payload = self.read_json()
            key = self.session_key()
            if route.path == "/api/session":
                token = payload.get("token")
                if not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,4096}", token.strip()):
                    raise RequestError(400, "Workspace Agent 액세스 토큰을 입력하세요.")
                agent_id = trigger_id(payload.get("trigger"))
                new_key = secrets.token_urlsafe(32)
                with self.server.lock:
                    self.server.sessions.pop(key, None)
                    self.server.sessions[new_key] = (agent_id, token.strip(), time.monotonic() + TTL, False)
                return self.send_json(200, {"configured":True, "verified":False}, new_key)
            if route.path == "/api/disconnect":
                with self.server.lock:
                    self.server.sessions.pop(key, None)
                return self.send_json(200, {"configured":False, "verified":False}, "")
            if route.path == "/api/agent":
                return self.submit_agent(key, payload)
            raise RequestError(404, "요청 경로를 찾을 수 없습니다.")
        except RequestError as error:
            self.send_json(error.status, {"error":str(error)})

    def submit_agent(self, key, payload):
        with self.server.lock:
            session = self.server.sessions.get(key)
        if not session or session[2] <= time.monotonic():
            raise RequestError(401, "Agent 연결 설정이 필요합니다.")
        message, request_id = payload.get("input"), payload.get("requestId")
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_INPUT:
            raise RequestError(400, f"분석 요청은 {MAX_INPUT:,}자 이하로 보내세요.")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", request_id):
            raise RequestError(400, "요청 식별자가 올바르지 않습니다.")
        try:
            url = run_agent(session, message, request_id)
        except RequestError as error:
            if error.status in (401, 403, 404, 409):
                with self.server.lock:
                    if self.server.sessions.get(key) == session:
                        self.server.sessions[key] = (*session[:3], False)
            raise
        with self.server.lock:
            if self.server.sessions.get(key) == session:
                self.server.sessions[key] = (*session[:3], True)
        self.send_json(202, {"conversation_url":url})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    with Server(args.port) as server:
        print(f"기술자료 워크벤치: {server.origin}", flush=True)
        if args.open_browser:
            threading.Timer(0.35, webbrowser.open, args=(server.origin,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
