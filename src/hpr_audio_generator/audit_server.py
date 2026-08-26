from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse
import webbrowser

from .ingredient_audit import (
    candidate_media_path,
    ingredient_catalog,
    ingredient_media_path,
    save_ingredient_review,
)


STATIC_ROOT = Path(__file__).resolve().parent / "static"


class IngredientAuditHandler(BaseHTTPRequestHandler):
    config_path: Path
    registry_path: Path | None

    def _json(self, status: HTTPStatus, payload: object) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _file(self, path: Path, *, allow_range: bool) -> None:
        if not path.is_file():
            raise ValueError(f"Missing media: {path}")
        size = path.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get("Range") if allow_range else None
        if range_header and range_header.startswith("bytes="):
            values = range_header[6:].split("-", 1)
            start = int(values[0] or 0)
            end = int(values[1] or end)
            if start < 0 or end < start or start >= size:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            end = min(end, size - 1)
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        )
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._file(STATIC_ROOT / "ingredients.html", allow_range=False)
            return
        if parsed.path == "/api/assets":
            self._json(
                HTTPStatus.OK,
                ingredient_catalog(
                    self.config_path, registry_path=self.registry_path
                ),
            )
            return
        if parsed.path.startswith("/ingredient-media/"):
            try:
                asset_id = unquote(parsed.path.removeprefix("/ingredient-media/"))
                self._file(
                    ingredient_media_path(self.config_path, asset_id), allow_range=True
                )
            except (ValueError, OSError) as error:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        if parsed.path.startswith("/candidate-media/"):
            try:
                if self.registry_path is None:
                    raise ValueError("Audio registry is unavailable")
                audio_id = unquote(parsed.path.removeprefix("/candidate-media/"))
                self._file(
                    candidate_media_path(self.registry_path, audio_id), allow_range=True
                )
            except (ValueError, OSError) as error:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        prefix = "/api/assets/"
        if not parsed.path.startswith(prefix):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1024 * 1024:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Review must be a JSON object")
            review = save_ingredient_review(
                self.config_path,
                asset_id=unquote(parsed.path.removeprefix(prefix)),
                decision=payload.get("decision", "active"),
                rating=payload.get("rating"),
                notes=payload.get("notes", ""),
            )
            self._json(HTTPStatus.CREATED, {"review": review})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})


def handler_for(
    config_path: Path, registry_path: Path | None
) -> type[IngredientAuditHandler]:
    class BoundIngredientAuditHandler(IngredientAuditHandler):
        pass

    BoundIngredientAuditHandler.config_path = config_path.resolve()
    BoundIngredientAuditHandler.registry_path = (
        registry_path.resolve() if registry_path else None
    )
    return BoundIngredientAuditHandler


def run_server(
    *,
    config_path: Path,
    registry_path: Path | None,
    host: str,
    port: int,
    open_browser: bool,
) -> None:
    server = ThreadingHTTPServer(
        (host, port), handler_for(config_path, registry_path)
    )
    url = f"http://{host}:{port}/"
    print(f"HPR Ingredient Audit is available at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HPR Ingredient Audit")
    parser.add_argument("--config", type=Path, default=Path("config/generator.xml"))
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_server(
        config_path=args.config,
        registry_path=args.registry,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
