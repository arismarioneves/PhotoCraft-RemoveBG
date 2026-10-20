import dataclasses
import hashlib
import http.server
import threading

import pytest

from removebg.models import MODELS, ModelError, ModelSpec, ensure_model, model_path


class _Server:
    def __init__(self):
        self.payload = b""
        self.requests = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests += 1
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.payload)))
                self.end_headers()
                self.wfile.write(outer.payload)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def spec(self, payload: bytes) -> ModelSpec:
        self.payload = payload
        url = f"http://127.0.0.1:{self.httpd.server_port}/model.onnx"
        return ModelSpec("t", "t.onnx", url, len(payload), hashlib.sha256(payload).hexdigest(), "MIT")


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.httpd.shutdown()


def test_downloads_and_verifies(server):
    spec = server.spec(b"x" * 1000)
    path = ensure_model(spec, report=lambda m: None)
    assert path.read_bytes() == b"x" * 1000 and server.requests == 1


def test_wrong_hash_raises_and_leaves_nothing(server):
    spec = dataclasses.replace(server.spec(b"x" * 1000), sha256="0" * 64)
    with pytest.raises(ModelError, match="does not match"):
        ensure_model(spec, report=lambda m: None)
    assert not model_path(spec).exists()
    assert not list(model_path(spec).parent.glob("*.part"))


def test_existing_file_with_right_size_is_not_downloaded(server):
    spec = server.spec(b"x" * 1000)
    model_path(spec).parent.mkdir(parents=True, exist_ok=True)
    model_path(spec).write_bytes(b"y" * 1000)
    ensure_model(spec, report=lambda m: None)
    assert server.requests == 0


def test_existing_file_with_wrong_size_is_replaced(server):
    spec = server.spec(b"x" * 1000)
    model_path(spec).parent.mkdir(parents=True, exist_ok=True)
    model_path(spec).write_bytes(b"short")
    assert ensure_model(spec, report=lambda m: None).read_bytes() == b"x" * 1000


def test_network_error_raises_model_error():
    spec = ModelSpec("t", "t.onnx", "http://127.0.0.1:9/nothing", 10, "0" * 64, "MIT")
    with pytest.raises(ModelError):
        ensure_model(spec, report=lambda m: None)
    assert not list(model_path(spec).parent.glob("*.part"))


def test_registry_pins_the_published_models():
    assert (MODELS["isnet"].size, MODELS["isnet"].sha256[:12]) == (178648008, "60920e99c454")
    assert (MODELS["rmbg-1.4"].size, MODELS["rmbg-1.4"].sha256[:12]) == (176153355, "8cafcf770b06")
