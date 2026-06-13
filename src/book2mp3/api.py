from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service


class Book2Mp3ApiServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], service: Book2Mp3Service) -> None:
        super().__init__(server_address, Book2Mp3ApiHandler)
        self.service = service


class Book2Mp3ApiHandler(BaseHTTPRequestHandler):
    server: Book2Mp3ApiServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/diagnostics":
                self._send_json(HTTPStatus.OK, self.server.service.diagnostics(include_runtime_probe=True))
                return
            if path == "/jobs":
                self._send_json(HTTPStatus.OK, {"jobs": self.server.service.list_jobs()})
                return
            if path == "/metadata/search":
                self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Use POST /metadata/search"})
                return
            if path == "/metadata/suggest":
                self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Use POST /metadata/suggest"})
                return
            if path == "/voices":
                self._send_json(HTTPStatus.OK, self.server.service.list_voices())
                return
            if path == "/profiles":
                self._send_json(HTTPStatus.OK, {"profiles": self.server.service.list_saved_profiles()})
                return
            profile_id = self._profile_id_from_path(path)
            if profile_id:
                self._send_json(HTTPStatus.OK, self.server.service.get_saved_profile(profile_id))
                return
            if path == "/presets":
                self._send_json(HTTPStatus.OK, {"presets": self.server.service.list_presets()})
                return
            job_id = self._job_id_from_path(path)
            if job_id:
                self._send_json(HTTPStatus.OK, self.server.service.get_job(job_id))
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json_body()
        if "profile_id" in payload and "saved_profile_id" not in payload:
            payload["saved_profile_id"] = payload["profile_id"]
        try:
            if path == "/jobs":
                self._send_json(HTTPStatus.CREATED, self.server.service.create_job(**payload))
                return
            if path == "/jobs/bulk":
                self._send_json(HTTPStatus.CREATED, {"jobs": self.server.service.create_jobs(**payload)})
                return
            if path == "/source/analyze":
                self._send_json(
                    HTTPStatus.OK,
                    self.server.service.analyze_source(str(payload.get("source_path", "") or "")),
                )
                return
            if path == "/metadata/suggest":
                self._send_json(
                    HTTPStatus.OK,
                    self.server.service.metadata_suggestions(str(payload.get("source_path", "") or "")),
                )
                return
            if path == "/metadata/search":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "results": self.server.service.search_book_metadata(
                            query=str(payload.get("query", "") or ""),
                            title=str(payload.get("title", "") or ""),
                            author=str(payload.get("author", "") or ""),
                            limit=int(payload.get("limit", 5) or 5),
                        )
                    },
                )
                return
            profile_status_id = self._profile_id_from_status_path(path)
            if profile_status_id:
                self._send_json(
                    HTTPStatus.OK,
                    self.server.service.update_saved_profile_status(profile_status_id, str(payload.get("status", ""))),
                )
                return
            if path == "/reset":
                self._send_json(HTTPStatus.OK, self.server.service.reset_workspace())
                return
            if path == "/jobs/run-next":
                result = self.server.service.run_next_job()
                if result is None:
                    self._send_json(HTTPStatus.OK, {"job": None})
                else:
                    self._send_json(HTTPStatus.OK, result)
                return
            suffix = self._job_action_suffix(path)
            job_id = self._job_id_from_action_path(path)
            if not suffix or not job_id:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})
                return
            if suffix == "enqueue":
                self._send_json(HTTPStatus.OK, self.server.service.enqueue_job(job_id))
                return
            if suffix == "run":
                self._send_json(HTTPStatus.OK, self.server.service.run_job(job_id))
                return
            if suffix == "retry":
                self._send_json(
                    HTTPStatus.OK,
                    self.server.service.retry_job(
                        job_id,
                        chunk_indexes=payload.get("chunk_indexes"),
                        reset_output=payload.get("reset_output", True),
                    ),
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        job_id = self._job_id_from_path(path)
        if not job_id:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})
            return
        try:
            self.server.service.delete_job(job_id)
            self._send_json(HTTPStatus.OK, {"deleted": job_id})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _job_id_from_path(self, path: str) -> str | None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 2 and parts[0] == "jobs":
            return parts[1]
        return None

    def _job_id_from_action_path(self, path: str) -> str | None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[0] == "jobs":
            return parts[1]
        return None

    def _job_action_suffix(self, path: str) -> str | None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[0] == "jobs":
            return parts[2]
        return None

    def _profile_id_from_path(self, path: str) -> str | None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 2 and parts[0] == "profiles":
            return parts[1]
        return None

    def _profile_id_from_status_path(self, path: str) -> str | None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[0] == "profiles" and parts[2] == "status":
            return parts[1]
        return None


def create_api_server(paths: AppPaths, host: str = "127.0.0.1", port: int = 8765) -> Book2Mp3ApiServer:
    service = Book2Mp3Service(paths)
    service.recover_interrupted_jobs()
    return Book2Mp3ApiServer((host, port), service)


def serve(paths: AppPaths, host: str = "127.0.0.1", port: int = 8765) -> int:
    server = create_api_server(paths, host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
