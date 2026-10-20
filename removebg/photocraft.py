"""Operations on a running PhotoCraft, driven through its control channel.

A request is a document whose last history step is the trigger plug-in. Each job undoes that
step and redoes it as the first command of a `coalesce` group, so the whole cut-out (including
the temporary indicator layer) becomes one undo step named after the plug-in.
"""
import base64
import time
from dataclasses import dataclass
from pathlib import Path

from .control import Control, ControlError
from .trigger import MENU_NAME, PLUGIN_ID, build_trigger

REQUIRED_COMMANDS = (
    "plugin.install", "plugin.run", "document.inspect", "document.activate", "layer.duplicate",
    "layer.setProps", "layer.copyToDocument", "layer.delete", "layer.select", "select.loadSelection",
    "layer.layerMask.revealSelection", "layer.layerMask.delete", "layer.newFillLayer.solidColor",
    "layer.smartFilter.delete", "file.close", "edit.undo",
)
INDICATOR_NAME = "Removing background…"
INDICATOR_COLOR = "#1e90ff"
INDICATOR_OPACITY = 0.35
SUPPORTED_MODES = {"rgb", "gray", "grayscale"}


class JobError(Exception):
    pass


@dataclass
class Request:
    index: int
    name: str
    path: str | None
    revision: int


@dataclass
class Job:
    request: Request
    layer: int
    key: str
    indicator: int | None
    visible: bool = True
    has_mask: bool = False


def missing_commands(ctl: Control) -> list[str]:
    available = {c["id"] for c in ctl.call("engine.commands")}
    return [c for c in REQUIRED_COMMANDS if c not in available]


def install_trigger(ctl: Control) -> None:
    ctl.run("plugin.install", {"data": base64.b64encode(build_trigger()).decode("ascii"), "replace": True})


def find_requests(documents: list[dict], histories: dict[int, list[str]],
                  handled: dict[tuple[str, str | None], tuple[str, ...]],
                  renamed: list[tuple[str, ...]] = ()) -> list[Request]:
    """A request is a history that changed since it was last seen and now ends in the trigger.

    The revision is no use here: selecting a layer or a mask raises it without a history step.
    A document seen for the first time counts too (it may have been opened and clicked while
    the helper was busy), unless its history is that of a document that just disappeared:
    Save As renames a document and keeps its history.
    """
    found = []
    for doc in sorted(documents, key=lambda d: d["index"]):
        steps = tuple(histories.get(doc["index"]) or ())
        before = handled.get((doc["name"], doc.get("path")))
        if before is None and steps in renamed:
            continue
        if steps != before and steps[-1:] == (MENU_NAME,):
            found.append(Request(doc["index"], doc["name"], doc.get("path"), doc["revision"]))
    return found


def poll_requests(ctl: Control, handled: dict, seen_revisions: dict) -> list[Request]:
    documents = _documents(ctl)
    open_keys = {(doc["name"], doc.get("path")) for doc in documents}
    vanished = [handled.pop(key) for key in list(handled) if key not in open_keys]
    for gone in [key for key in seen_revisions if key not in open_keys]:
        del seen_revisions[gone]
    changed, histories = [], {}
    for doc in documents:
        key = (doc["name"], doc.get("path"))
        if seen_revisions.get(key) == doc["revision"]:
            continue
        try:
            histories[doc["index"]] = ctl.run("document.inspect", {"document": doc["index"]})["history"]
        except ControlError:
            continue  # closed since the document list was read
        seen_revisions[key] = doc["revision"]
        changed.append(doc)
    requests = find_requests(changed, histories, handled, vanished)
    for doc in changed:
        handled[(doc["name"], doc.get("path"))] = tuple(histories[doc["index"]])
    return requests


def begin(ctl: Control, req: Request) -> Job:
    _activate(ctl, req)
    doc = ctl.run("document.inspect")
    if str(doc.get("mode", "")).lower() not in SUPPORTED_MODES:
        raise JobError("Remove Background (AI) works on RGB and Grayscale documents. "
                       "Convert the document with Image › Mode first.")
    layer = doc["activeLayer"]
    info = _layer(doc, layer)
    key = f"removebg-{time.time_ns()}"
    if doc["history"][-1:] == [MENU_NAME]:
        ctl.run("edit.undo")
    ctl.run("plugin.run", {"id": PLUGIN_ID, "coalesce": key})
    if info.get("kind") == "Smart Object":
        ctl.run("layer.smartFilter.delete", {"layer": layer, "coalesce": key})
    # The indicator covers the whole canvas: clipping it to the layer would cost another
    # PhotoCraft command (about half a second each on a CPU-rendered canvas).
    indicator = ctl.run("layer.newFillLayer.solidColor", {"color": INDICATOR_COLOR, "coalesce": key})["layer"]
    ctl.run("layer.setProps", {"layer": indicator, "name": INDICATOR_NAME, "opacity": INDICATOR_OPACITY,
                               "coalesce": key})
    return Job(req, layer, key, indicator, info.get("visible", True), bool(info.get("hasMask")))


def export_layer(ctl: Control, job: Job, exchange: Path) -> Path:
    copy = ctl.run("layer.duplicate", {"layer": job.layer, "document": "new", "documentName": job.key})
    temp = copy["document"]
    copy_layer = copy["layers"][0]
    if not job.visible:
        ctl.run("layer.setProps", {"layer": copy_layer, "visible": True})
    if job.has_mask:
        ctl.run("layer.layerMask.delete", {"layer": copy_layer})
    name = f"{job.key}-in.png"
    ctl.call("app.save", {"path": name})
    ctl.run("file.close", {"document": temp})
    _activate(ctl, job.request)
    return exchange / name


def apply_mask(ctl: Control, job: Job, matte_png: Path, exchange: Path) -> tuple[str, ...]:
    origin = _resolve(ctl, job.request)
    ctl.call("app.open", {"path": matte_png.relative_to(exchange).as_posix()})
    temp = ctl.call("ui.inspect")["session"]["active"]
    new = ctl.run("layer.copyToDocument", {"document": origin, "source": temp, "coalesce": job.key})["layers"][0]
    ctl.run("file.close", {"document": temp})
    # The temporary document opened last, so closing it leaves the origin's index unchanged.
    ctl.run("document.activate", {"document": origin})
    ctl.run("select.loadSelection", {"channel": "transparency", "layer": new, "coalesce": job.key})
    ctl.run("layer.layerMask.revealSelection", {"layer": job.layer, "coalesce": job.key})
    ctl.run("layer.delete", {"layer": new, "coalesce": job.key})
    if job.indicator is not None:
        ctl.run("layer.delete", {"layer": job.indicator, "coalesce": job.key})
    ctl.run("layer.select", {"layer": job.layer, "coalesce": job.key})
    for leftover in exchange.glob(f"{job.key}-*"):
        leftover.unlink(missing_ok=True)
    return tuple(ctl.run("document.inspect")["history"])


def abort(ctl: Control, job: Job) -> None:
    try:
        _activate(ctl, job.request)
        if job.indicator is not None:
            ctl.run("layer.delete", {"layer": job.indicator, "coalesce": job.key})
        ctl.run("layer.select", {"layer": job.layer, "coalesce": job.key})
    except (ControlError, JobError):
        pass


def remove_leftover_indicators(ctl: Control) -> int:
    session = ctl.call("ui.inspect")["session"]
    removed = 0
    for doc in session["documents"]:
        found = [item["id"] for item in _walk(ctl.run("document.inspect", {"document": doc["index"]})["layers"])
                 if item.get("kind") == "Fill" and item.get("name") == INDICATOR_NAME]
        if found:
            ctl.run("document.activate", {"document": doc["index"]})
            for layer in found:
                ctl.run("layer.delete", {"layer": layer})
                removed += 1
    if removed and session.get("active") is not None:
        ctl.run("document.activate", {"document": session["active"]})
    return removed


def history_of(ctl: Control, req: Request) -> tuple[str, ...] | None:
    try:
        index = _resolve(ctl, req)
        return tuple(ctl.run("document.inspect", {"document": index})["history"])
    except (JobError, ControlError):
        return None


def _documents(ctl: Control) -> list[dict]:
    return ctl.call("ui.inspect")["session"]["documents"]


def _find(documents: list[dict], req: Request) -> int:
    for doc in documents:
        if (doc["name"], doc.get("path")) == (req.name, req.path):
            return doc["index"]
    raise JobError("The document was closed.")


def _resolve(ctl: Control, req: Request) -> int:
    return _find(_documents(ctl), req)


def _activate(ctl: Control, req: Request) -> int:
    session = ctl.call("ui.inspect")["session"]
    index = _find(session["documents"], req)
    if session.get("active") != index:
        ctl.run("document.activate", {"document": index})
    return index


def _walk(layers: list[dict]):
    for layer in layers:
        yield layer
        yield from _walk(layer.get("children") or [])


def _layer(doc: dict, layer_id: int) -> dict:
    return next((item for item in _walk(doc["layers"]) if item["id"] == layer_id), {})
