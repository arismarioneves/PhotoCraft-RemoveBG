import json
import socket
import threading
from unittest.mock import ANY

import pytest

from removebg.control import Control, ControlError, port_open


class _FakePhotoCraft:
    default_result = {"value": 42}

    def __init__(self):
        self.frames = []
        self.auth_error = None
        self.errors = {}
        self.stray = False
        self.conns = []
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def refuse_auth(self, message):
        self.auth_error = message

    def reply_error(self, method, message):
        self.errors[method] = message

    def prepend_stray_reply(self):
        self.stray = True

    def drop_connections(self):
        for c in self.conns:
            c.shutdown(socket.SHUT_RDWR)
            c.close()

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            for line in conn.makefile("rb"):
                frame = json.loads(line)
                self.frames.append(frame)
                if frame["method"] == "auth":
                    reply = ({"id": frame["id"], "ok": False, "error": self.auth_error} if self.auth_error
                             else {"id": frame["id"], "ok": True, "result": {"authenticated": True}})
                elif frame["method"] in self.errors:
                    reply = {"id": frame["id"], "ok": False, "error": self.errors[frame["method"]]}
                else:
                    if self.stray:
                        conn.sendall(b'{"id": "other", "ok": true, "result": null}\n')
                    reply = {"id": frame["id"], "ok": True, "result": self.default_result}
                conn.sendall((json.dumps(reply) + "\n").encode())
        except OSError:
            pass


@pytest.fixture
def fake():
    f = _FakePhotoCraft()
    yield f
    f.server.close()


def test_first_frame_is_auth_with_token(fake):
    Control(fake.port, "ab" * 32)
    assert fake.frames[0] == {"id": ANY, "method": "auth", "params": {"token": "ab" * 32}}


def test_refused_token_raises_control_error(fake):
    fake.refuse_auth("bad token")
    with pytest.raises(ControlError, match="bad token"):
        Control(fake.port, "00" * 32)


def test_error_reply_raises_with_photocraft_message(fake):
    fake.reply_error("engine.execute", "command `x` is not available right now")
    with pytest.raises(ControlError, match="not available right now"):
        Control(fake.port, "ab" * 32).run("x")


def test_replies_with_other_ids_are_skipped(fake):
    fake.prepend_stray_reply()
    assert Control(fake.port, "ab" * 32).call("ui.inspect") == fake.default_result


def test_closed_connection_raises_oserror(fake):
    c = Control(fake.port, "ab" * 32)
    fake.drop_connections()
    with pytest.raises(OSError):
        c.call("ui.inspect")


def test_port_open(fake):
    assert port_open(fake.port)
    fake.server.close()
    assert not port_open(fake.port)
