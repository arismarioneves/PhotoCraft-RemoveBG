import time

import pytest
from PIL import Image

from removebg.photocraft import (
    INDICATOR_NAME, JobError, Request, abort, apply_mask, begin, export_layer, find_requests, poll_requests,
    revision_of,
)
from removebg.control import ControlError
from removebg.trigger import MENU_NAME, PLUGIN_ID


def test_new_trigger_is_a_request():
    docs = [{"index": 0, "name": "a.jpg", "path": "a.jpg", "revision": 2}]
    assert find_requests(docs, {0: ["Open", MENU_NAME]}, {}) == [Request(0, "a.jpg", "a.jpg", 2)]


def test_handled_revision_is_not_a_request():
    docs = [{"index": 0, "name": "a.jpg", "path": "a.jpg", "revision": 5}]
    assert find_requests(docs, {0: ["Open", MENU_NAME]}, {("a.jpg", "a.jpg"): 5}) == []


def test_other_last_step_is_not_a_request():
    docs = [{"index": 0, "name": "a.jpg", "path": "a.jpg", "revision": 3}]
    assert find_requests(docs, {0: ["Open", "Brush Tool"]}, {}) == []


def test_triggers_in_two_documents_come_in_index_order():
    docs = [{"index": 1, "name": "b", "path": None, "revision": 4}, {"index": 0, "name": "a", "path": None, "revision": 2}]
    hist = {0: ["Open", MENU_NAME], 1: ["Open", MENU_NAME]}
    assert [r.index for r in find_requests(docs, hist, {})] == [0, 1]


class _DocumentClosedWhilePolling:
    """Lists two documents, then the first one is gone when it is inspected."""

    def call(self, method, params=None):
        return {"session": {"documents": [{"index": 0, "name": "a", "path": "a", "revision": 3},
                                          {"index": 1, "name": "b", "path": "b", "revision": 5}]}}

    def run(self, command, params=None):
        if params["document"] == 0:
            raise ControlError("command `document.inspect` is not available right now: no document open")
        return {"history": ["Open", MENU_NAME]}


def test_document_closed_while_polling_is_skipped():
    assert [r.name for r in poll_requests(_DocumentClosedWhilePolling(), {}, {})] == ["b"]


# --- live PhotoCraft -------------------------------------------------------------------------

def _index(app, photo):
    return next(d["index"] for d in app.call("ui.inspect")["session"]["documents"]
                if (d["name"], d.get("path")) == (photo.name, photo.path))


def _walk(layers):
    for layer in layers:
        yield layer
        yield from _walk(layer.get("children") or [])


def layers(app, doc=None):
    params = {} if doc is None else {"document": _index(app, doc)}
    return list(_walk(app.run("document.inspect", params)["layers"]))


def layer_info(app, layer, doc=None):
    return next(item for item in layers(app, doc) if item["id"] == layer)


def history(app, doc=None):
    params = {} if doc is None else {"document": _index(app, doc)}
    return app.run("document.inspect", params)["history"]


def activate(app, photo):
    app.run("document.activate", {"document": _index(app, photo)})


def trigger(app, photo) -> Request:
    activate(app, photo)
    app.call("ui.menu.invoke", {"id": f"plugin.filter.{PLUGIN_ID}"})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for req in poll_requests(app, {}, {}):
            if (req.name, req.path) == (photo.name, photo.path):
                return req
        time.sleep(0.2)
    pytest.fail("the trigger never showed up in the history")


def write_half(exported, exchange, key, side):
    w, h = Image.open(exported).size
    mask = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    mask.paste((255, 255, 255, 255), (0, 0, w // 2, h) if side == "left" else (w // 2, 0, w, h))
    path = exchange / f"{key}-matte.png"
    mask.save(path)
    return path


def run_job(app, exchange, photo, side="left"):
    job = begin(app, trigger(app, photo))
    exported = export_layer(app, job, exchange)
    apply_mask(app, job, write_half(exported, exchange, job.key, side), exchange)
    return job


def mask_bounds(app, layer):
    app.run("select.loadSelection", {"channel": "mask", "layer": layer})
    bounds = app.run("document.inspect")["selectionBounds"]
    app.run("select.deselect")
    return bounds


def no_indicator(app, doc=None):
    return not [item for item in layers(app, doc) if item["name"] == INDICATOR_NAME]


@pytest.mark.photocraft
def test_round_trip_is_one_undo_step(app, exchange, photo):
    before = history(app, photo)
    job = run_job(app, exchange, photo)
    assert history(app, photo) == before + [MENU_NAME]
    assert layer_info(app, job.layer, photo)["hasMask"]
    app.run("edit.undo")
    assert not layer_info(app, job.layer, photo)["hasMask"] and history(app, photo) == before
    app.run("edit.redo")
    assert mask_bounds(app, job.layer) == [0, 0, photo.w // 2, photo.h]


@pytest.mark.photocraft
def test_indicator_exists_during_job_and_is_gone_after(app, exchange, photo):
    job = begin(app, trigger(app, photo))
    ind = [item for item in layers(app, photo) if item["name"] == INDICATOR_NAME]
    assert len(ind) == 1 and ind[0]["kind"] == "Fill"
    exported = export_layer(app, job, exchange)
    apply_mask(app, job, write_half(exported, exchange, job.key, "left"), exchange)
    assert no_indicator(app, photo)


@pytest.mark.photocraft
def test_smart_object_keeps_no_smart_filter(app, exchange, photo):
    activate(app, photo)
    app.run("layer.smartObjects.convertToSmartObject", {"layer": app.run("document.inspect")["activeLayer"]})
    job = run_job(app, exchange, photo)
    assert layer_info(app, job.layer, photo)["smartFilters"] == []
    assert layer_info(app, job.layer, photo)["hasMask"]
    assert history(app, photo)[-1] == MENU_NAME and history(app, photo).count(MENU_NAME) == 1


@pytest.mark.photocraft
def test_existing_mask_is_replaced(app, exchange, photo):
    run_job(app, exchange, photo, "left")
    job = run_job(app, exchange, photo, "right")
    assert mask_bounds(app, job.layer) == [photo.w // 2, 0, photo.w - photo.w // 2, photo.h]


@pytest.mark.photocraft
def test_hidden_layer_exports_pixels(app, exchange, photo):
    activate(app, photo)
    app.run("layer.setProps", {"layer": app.run("document.inspect")["activeLayer"], "visible": False})
    job = begin(app, trigger(app, photo))
    exported = export_layer(app, job, exchange)
    assert Image.open(exported).convert("RGBA").getchannel("A").getextrema()[1] == 255
    abort(app, job)


@pytest.mark.photocraft
def test_mask_lands_on_original_after_tab_switch(app, exchange, photo, other_photo):
    job = begin(app, trigger(app, photo))
    exported = export_layer(app, job, exchange)
    activate(app, other_photo)
    apply_mask(app, job, write_half(exported, exchange, job.key, "left"), exchange)
    assert layer_info(app, job.layer, photo)["hasMask"]
    assert not any(item["hasMask"] for item in layers(app, other_photo))


@pytest.mark.photocraft
def test_abort_leaves_layer_unchanged(app, exchange, photo):
    job = begin(app, trigger(app, photo))
    abort(app, job)
    assert not layer_info(app, job.layer, photo)["hasMask"] and no_indicator(app, photo)


@pytest.mark.photocraft
def test_stale_request_revision_still_gives_one_step(app, exchange, photo):
    before = history(app, photo)
    req = trigger(app, photo)
    job = begin(app, Request(req.index, req.name, req.path, req.revision - 1))
    exported = export_layer(app, job, exchange)
    apply_mask(app, job, write_half(exported, exchange, job.key, "left"), exchange)
    assert history(app, photo) == before + [MENU_NAME]


@pytest.mark.photocraft
def test_lab_document_is_refused(app):
    app.run("file.new", {"mode": "lab", "width": 64, "height": 64, "name": "lab-test"})
    try:
        doc = next(d for d in app.call("ui.inspect")["session"]["documents"] if d["name"] == "lab-test")
        with pytest.raises(JobError, match="RGB and Grayscale"):
            begin(app, Request(doc["index"], doc["name"], doc.get("path"), doc["revision"]))
    finally:
        doc = next(d for d in app.call("ui.inspect")["session"]["documents"] if d["name"] == "lab-test")
        app.run("file.close", {"document": doc["index"]})


@pytest.mark.photocraft
def test_revision_of_follows_the_document_and_is_none_once_closed(app, exchange):
    from conftest import _close_photo, _open_photo
    p = _open_photo(app, exchange, "low-contrast.jpg")
    req = trigger(app, p)
    app.run("edit.undo")
    current = next(d["revision"] for d in app.call("ui.inspect")["session"]["documents"] if d["name"] == p.name)
    assert revision_of(app, req) == current != req.revision
    _close_photo(app, p)
    assert revision_of(app, req) is None
