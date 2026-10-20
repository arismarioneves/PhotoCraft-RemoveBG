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
    "layer.createClippingMask", "layer.smartFilter.delete", "file.close", "edit.undo",
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


def missing_commands(ctl: Control) -> list[str]:
    available = {c["id"] for c in ctl.call("engine.commands")}
    return [c for c in REQUIRED_COMMANDS if c not in available]


def install_trigger(ctl: Control) -> None:
    ctl.run("plugin.install", {"data": base64.b64encode(build_trigger()).decode("ascii"), "replace": True})


def find_requests(documents: list[dict], histories: dict[int, list[str]],
                  handled: dict[tuple[str, str | None], int]) -> list[Request]:
    found = []
    for doc in sorted(documents, key=lambda d: d["index"]):
        steps = histories.get(doc["index"]) or []
        if steps[-1:] == [MENU_NAME] and handled.get((doc["name"], doc.get("path"))) != doc["revision"]:
            found.append(Request(doc["index"], doc["name"], doc.get("path"), doc["revision"]))
    return found


def poll_requests(ctl: Control, handled: dict, seen_revisions: dict) -> list[Request]:
    documents = _documents(ctl)
    changed, histories = [], {}
    for doc in documents:
        key = (doc["name"], doc.get("path"))
        if seen_revisions.get(key) == doc["revision"]:
            continue
        seen_revisions[key] = doc["revision"]
        histories[doc["index"]] = ctl.run("document.inspect", {"document": doc["index"]})["history"]
        changed.append(doc)
    return find_requests(changed, histories, handled)


def begin(ctl: Control, req: Request) -> Job:
    _activate(ctl, req)
    doc = ctl.run("document.inspect")
    if str(doc.get("mode", "")).lower() not in SUPPORTED_MODES:
        raise JobError("Remove Background (AI) works on RGB and Grayscale documents. "
                       "Convert the document with Image › Mode first.")
    layer = doc["activeLayer"]
    info = _layer(doc, layer)
    key = f"removebg-{time.time_ns()}"
    if doc["history"][-1:] == [MENU_NAME] and doc["revision"] == req.revision:
        ctl.run("edit.undo")
    ctl.run("plugin.run", {"id": PLUGIN_ID, "coalesce": key})
    if info.get("kind") == "Smart Object":
        ctl.run("layer.smartFilter.delete", {"layer": layer, "coalesce": key})
    indicator = ctl.run("layer.newFillLayer.solidColor", {"color": INDICATOR_COLOR, "coalesce": key})["layer"]
    ctl.run("layer.setProps", {"layer": indicator, "name": INDICATOR_NAME, "opacity": INDICATOR_OPACITY,
                               "coalesce": key})
    ctl.run("layer.createClippingMask", {"layer": indicator, "coalesce": key})
    ctl.run("layer.select", {"layer": layer, "coalesce": key})
    return Job(req, layer, key, indicator)


def export_layer(ctl: Control, job: Job, exchange: Path) -> Path:
    _activate(ctl, job.request)
    info = _layer(ctl.run("document.inspect"), job.layer)
    copy = ctl.run("layer.duplicate", {"layer": job.layer, "document": "new", "documentName": job.key})
    temp = copy["document"]
    copy_layer = copy["layers"][0]
    if not info.get("visible", True):
        ctl.run("layer.setProps", {"layer": copy_layer, "visible": True})
    if info.get("hasMask"):
        ctl.run("layer.layerMask.delete", {"layer": copy_layer})
    name = f"{job.key}-in.png"
    ctl.call("app.save", {"path": name})
    ctl.run("file.close", {"document": temp})
    _activate(ctl, job.request)
    return exchange / name


def apply_mask(ctl: Control, job: Job, matte_png: Path, exchange: Path) -> int:
    origin = _resolve(ctl, job.request)
    ctl.call("app.open", {"path": matte_png.relative_to(exchange).as_posix()})
    temp = ctl.call("ui.inspect")["session"]["active"]
    new = ctl.run("layer.copyToDocument", {"document": origin, "source": temp, "coalesce": job.key})["layers"][0]
    ctl.run("file.close", {"document": temp})
    _activate(ctl, job.request)
    ctl.run("select.loadSelection", {"channel": "transparency", "layer": new, "coalesce": job.key})
    ctl.run("layer.layerMask.revealSelection", {"layer": job.layer, "coalesce": job.key})
    ctl.run("layer.delete", {"layer": new, "coalesce": job.key})
    if job.indicator is not None:
        ctl.run("layer.delete", {"layer": job.indicator, "coalesce": job.key})
    ctl.run("layer.select", {"layer": job.layer, "coalesce": job.key})
    for leftover in exchange.glob(f"{job.key}-*"):
        leftover.unlink(missing_ok=True)
    return ctl.run("document.inspect")["revision"]


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


def _documents(ctl: Control) -> list[dict]:
    return ctl.call("ui.inspect")["session"]["documents"]


def _resolve(ctl: Control, req: Request) -> int:
    for doc in _documents(ctl):
        if (doc["name"], doc.get("path")) == (req.name, req.path):
            return doc["index"]
    raise JobError("The document was closed.")


def _activate(ctl: Control, req: Request) -> int:
    index = _resolve(ctl, req)
    ctl.run("document.activate", {"document": index})
    return index


def _walk(layers: list[dict]):
    for layer in layers:
        yield layer
        yield from _walk(layer.get("children") or [])


def _layer(doc: dict, layer_id: int) -> dict:
    return next((item for item in _walk(doc["layers"]) if item["id"] == layer_id), {})
