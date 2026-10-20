import json
import socket
from typing import Any

_MAX_LINE = 8 << 20


class ControlError(Exception):
    pass


def port_open(port: int, timeout: float = 0.3) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Control:
    def __init__(self, port: int, token: str, timeout: float = 65.0) -> None:
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self._reader = self._sock.makefile("rb")
        self._next_id = 0
        try:
            self._request("auth", {"token": token}, "auth")
        except BaseException:
            self.close()
            raise

    def call(self, method: str, params: dict | None = None) -> Any:
        self._next_id += 1
        return self._request(method, params or {}, self._next_id)

    def run(self, command: str, params: dict | None = None) -> Any:
        return self.call("engine.execute", {"command": command, "params": params or {}})

    def close(self) -> None:
        for closer in (self._reader.close, self._sock.close):
            try:
                closer()
            except OSError:
                pass

    def _request(self, method: str, params: dict, request_id) -> Any:
        frame = {"id": request_id, "method": method, "params": params}
        self._sock.sendall((json.dumps(frame) + "\n").encode())
        while True:
            line = self._reader.readline(_MAX_LINE + 1)
            if not line:
                raise ConnectionError("PhotoCraft closed the control connection")
            if len(line) > _MAX_LINE:
                raise ConnectionError("PhotoCraft sent a reply larger than 8 MiB")
            reply = json.loads(line)
            if reply.get("id") != request_id:
                continue
            if not reply.get("ok"):
                raise ControlError(str(reply.get("error")))
            return reply.get("result")
