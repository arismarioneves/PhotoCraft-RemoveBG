"""Builds the PhotoCraft filter plug-in (ABI v1) that only marks the menu click.

The module does nothing to the pixels: running it records an undo step named after the
plug-in, which is what the helper watches for. Hand-assembled so the project needs no
WebAssembly toolchain.
"""
import json

from . import __version__

PLUGIN_ID = "photocraft-removebg"
MENU_NAME = "Remove Background (AI)"

_I32, _I64 = 0x7F, 0x7E
_MANIFEST_AT = 1024


def _uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _sleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        done = (n == 0 and not b & 0x40) or (n == -1 and b & 0x40)
        out.append(b | (0 if done else 0x80))
        if done:
            return bytes(out)


def _vec(items: list[bytes]) -> bytes:
    return _uleb(len(items)) + b"".join(items)


def _name(s: str) -> bytes:
    b = s.encode()
    return _uleb(len(b)) + b


def _section(sid: int, payload: bytes) -> bytes:
    return bytes([sid]) + _uleb(len(payload)) + payload


def build_trigger(version: str = __version__) -> bytes:
    manifest = json.dumps({
        "id": PLUGIN_ID,
        "name": MENU_NAME,
        "version": version,
        "kind": "filter",
        "author": "PhotoCraft-RemoveBG contributors",
        "description": "Removes the background of the active layer with a local AI model. Works when "
                       "PhotoCraft is opened with the \"PhotoCraft (Remove Background)\" shortcut.",
    }, ensure_ascii=False, separators=(",", ":")).encode()
    heap = (_MANIFEST_AT + len(manifest) + 15) & ~15

    types = _vec([
        b"\x60" + _vec([]) + _vec([bytes([_I32])]),            # pc_abi_version
        b"\x60" + _vec([]) + _vec([bytes([_I64])]),            # pc_manifest
        b"\x60" + _vec([bytes([_I32])]) + _vec([bytes([_I32])]),  # pc_alloc
        b"\x60" + _vec([bytes([_I32])] * 8) + _vec([bytes([_I32])]),  # pc_filter
    ])
    functions = _vec([_uleb(0), _uleb(1), _uleb(2), _uleb(3)])
    memory = _vec([b"\x00" + _uleb(1)])
    globals_ = _vec([bytes([_I32, 0x01]) + b"\x41" + _sleb(heap) + b"\x0b"])
    exports = _vec([
        _name("memory") + b"\x02" + _uleb(0),
        _name("pc_abi_version") + b"\x00" + _uleb(0),
        _name("pc_manifest") + b"\x00" + _uleb(1),
        _name("pc_alloc") + b"\x00" + _uleb(2),
        _name("pc_filter") + b"\x00" + _uleb(3),
    ])
    abi_version = b"\x00\x41\x01\x0b"
    manifest_ptr = b"\x00\x42" + _sleb((len(manifest) << 32) | _MANIFEST_AT) + b"\x0b"
    # Bump allocator: the host writes a whole band (up to ~4 MiB of f32) here, so grow on demand.
    alloc = (
        b"\x01\x01\x7f"
        b"\x23\x00\x21\x01"
        b"\x20\x01\x20\x00\x6a\x41\x07\x6a\x41\x78\x71\x24\x00"
        b"\x02\x40"
        b"\x23\x00\x3f\x00\x41\x10\x74\x4d\x0d\x00"
        b"\x23\x00\x3f\x00\x41\x10\x74\x6b\x41\xff\xff\x03\x6a\x41\x10\x76"
        b"\x40\x00\x41\x7f\x46"
        b"\x04\x40\x41\x00\x0f\x0b"
        b"\x0b"
        b"\x20\x01\x0b"
    )
    filter_ = b"\x00\x41\x00\x0b"
    code = _vec([_uleb(len(body)) + body for body in (abi_version, manifest_ptr, alloc, filter_)])
    data = _vec([b"\x00\x41" + _sleb(_MANIFEST_AT) + b"\x0b" + _uleb(len(manifest)) + manifest])

    return (b"\x00asm\x01\x00\x00\x00"
            + _section(1, types) + _section(3, functions) + _section(5, memory)
            + _section(6, globals_) + _section(7, exports) + _section(10, code) + _section(11, data))
