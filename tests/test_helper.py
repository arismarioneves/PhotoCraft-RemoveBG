import pytest
from PIL import Image

from removebg.config import Config, log_path
from removebg.control import ControlError
from removebg.helper import Helper, user_message
from removebg.models import ModelError
from removebg.photocraft import Job, JobError, Request

MEMORY = "Not enough memory to remove the background. Close other programs and try again."


def req(revision):
    return Request(0, "a.jpg", "a.jpg", revision)


class FakeOps:
    def __init__(self, requests=(), poll_error=None, begin_error=None):
        self.queue = list(requests)
        self.poll_error = poll_error
        self.begin_error = begin_error
        self.aborted, self.applied, self.polled_handled = [], [], []

    def poll_requests(self, ctl, handled, seen):
        if self.poll_error:
            raise self.poll_error
        self.polled_handled.append(dict(handled))
        return self.queue.pop(0) if self.queue else []

    def begin(self, ctl, request):
        if self.begin_error:
            raise self.begin_error
        return Job(request, layer=1, key=f"k{request.revision}", indicator=None)

    def export_layer(self, ctl, job, exchange):
        exchange.mkdir(parents=True, exist_ok=True)
        path = exchange / f"{job.key}-in.png"
        Image.new("RGBA", (8, 6), (10, 20, 30, 255)).save(path)
        return path

    def apply_mask(self, ctl, job, matte_png, exchange):
        assert Image.open(matte_png).size == (8, 6)
        self.applied.append(job.request.revision)
        return job.request.revision + 100

    def abort(self, ctl, job):
        self.aborted.append(job.request.revision)

    def revision_of(self, ctl, request):
        return request.revision + 50


class FakeMatter:
    def __init__(self, fail_on_call=None, error=None):
        self.calls = 0
        self.fail_on_call = fail_on_call
        self.error = error

    def matte(self, image):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise self.error
        return Image.new("L", image.size, 255)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_failure_notifies_and_next_request_still_runs():
    ops = FakeOps(requests=[[req(1)], [req(2)]])
    matter = FakeMatter(fail_on_call=1, error=RuntimeError("[ONNXRuntimeError] : 6 : bad allocation"))
    notes = []
    h = Helper(Config(), ctl=None, ops=ops, matter_factory=lambda model: matter, notify=notes.append)
    h.step()
    h.step()
    assert notes == [MEMORY]
    assert ops.aborted == [1] and ops.applied == [2]


def test_failed_request_is_marked_with_the_revision_after_cleanup():
    ops = FakeOps(requests=[[req(1)], []])
    h = Helper(Config(), ctl=None, ops=ops, notify=lambda m: None,
               matter_factory=lambda model: FakeMatter(fail_on_call=1, error=ValueError("boom")))
    h.step()
    h.step()
    assert ops.polled_handled[-1] == {("a.jpg", "a.jpg"): 51}


def test_successful_request_is_marked_with_the_revision_after_the_mask():
    ops = FakeOps(requests=[[req(3)], []])
    h = Helper(Config(), ctl=None, ops=ops, matter_factory=lambda model: FakeMatter(), notify=lambda m: None)
    h.step()
    h.step()
    assert ops.polled_handled[-1] == {("a.jpg", "a.jpg"): 103}


def test_refused_document_shows_the_reason_without_abort():
    ops = FakeOps(requests=[[req(1)]], begin_error=JobError("works on RGB and Grayscale documents"))
    notes = []
    h = Helper(Config(), ctl=None, ops=ops, matter_factory=lambda model: FakeMatter(), notify=notes.append)
    h.step()
    assert notes == ["works on RGB and Grayscale documents"] and ops.aborted == []


def test_oserror_propagates_for_reconnect():
    h = Helper(Config(), ctl=None, ops=FakeOps(poll_error=ConnectionResetError()), notify=lambda m: None)
    with pytest.raises(OSError):
        h.step()


def test_model_is_unloaded_after_ten_idle_minutes():
    clock = FakeClock()
    created = []
    h = Helper(Config(), ctl=None, ops=FakeOps(requests=[[req(1)], [], [req(2)]]),
               matter_factory=lambda model: created.append(1) or FakeMatter(), notify=lambda m: None, clock=clock)
    h.step()
    clock.advance(601)
    h.step()
    h.step()
    assert len(created) == 2


def test_model_stays_loaded_while_in_use():
    clock = FakeClock()
    created = []
    h = Helper(Config(), ctl=None, ops=FakeOps(requests=[[req(1)], [req(2)]]),
               matter_factory=lambda model: created.append(1) or FakeMatter(), notify=lambda m: None, clock=clock)
    h.step()
    clock.advance(300)
    h.step()
    assert len(created) == 1


def test_unlicensed_rmbg_warns_once_and_uses_isnet():
    asked, notes = [], []
    h = Helper(Config(model="rmbg-1.4"), ctl=None, ops=FakeOps(requests=[[req(1)], [req(2)]]),
               matter_factory=lambda model: asked.append(model) or FakeMatter(), notify=notes.append)
    h.step()
    h.step()
    assert asked == ["isnet"] and len(notes) == 1 and "install.ps1 -Model rmbg-1.4" in notes[0]


def test_user_message_for_unknown_error_points_to_log():
    assert str(log_path()) in user_message(ValueError("x"))


def test_user_messages_for_known_errors():
    assert user_message(MemoryError()) == MEMORY
    assert user_message(ModelError("download failed")) == "download failed"
    assert user_message(ControlError("no layer")) == "PhotoCraft refused a step: no layer"
