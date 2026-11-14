import json
from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from app.config import settings
from app.services import v1_limiter as lim


class FakeBlob:
    def __init__(self):
        self.state = None
        self.generation = 0
        self.fail_once = False

    def reload(self, **_):
        if self.state is None:
            raise NotFound("missing")

    def download_as_bytes(self, if_generation_match, **_):
        if if_generation_match != self.generation:
            raise PreconditionFailed("changed")
        return json.dumps(self.state).encode()

    def upload_from_string(self, data, if_generation_match, **_):
        if self.fail_once:
            self.fail_once = False
            raise PreconditionFailed("raced")
        if if_generation_match != self.generation:
            raise PreconditionFailed("changed")
        self.state = json.loads(data)
        self.generation += 1


@pytest.fixture
def gate(monkeypatch):
    blob = FakeBlob()
    monkeypatch.setattr(lim, "_blob", lambda: blob)
    monkeypatch.setattr(settings, "echryn_v1_limits_enabled", True)
    monkeypatch.setattr(settings, "echryn_public_enabled", True)
    monkeypatch.setattr(settings, "echryn_v1_hourly_limit", 2)
    monkeypatch.setattr(settings, "echryn_v1_daily_limit", 3)
    monkeypatch.setattr(settings, "echryn_v1_lease_seconds", 360)
    return blob


@pytest.mark.asyncio
async def test_atomic_hourly_cap_and_release(gate):
    for _ in range(2):
        async with lim.extraction_gate():
            assert gate.state["active"]["token"]
        assert gate.state["active"] is None
    with pytest.raises(lim.V1GateError, match="v1_hourly_limit_reached") as err:
        async with lim.extraction_gate():
            pass
    assert err.value.status_code == 429
    assert gate.state["daily"] == 2


@pytest.mark.asyncio
async def test_global_busy_lease(gate):
    async with lim.extraction_gate():
        with pytest.raises(lim.V1GateError, match="v1_extraction_busy"):
            async with lim.extraction_gate():
                pass
    assert gate.state["daily"] == 1


@pytest.mark.asyncio
async def test_daily_cap(gate, monkeypatch):
    monkeypatch.setattr(settings, "echryn_v1_hourly_limit", 100)
    monkeypatch.setattr(settings, "echryn_v1_daily_limit", 2)
    for _ in range(2):
        async with lim.extraction_gate():
            pass
    with pytest.raises(lim.V1GateError, match="v1_daily_limit_reached"):
        async with lim.extraction_gate():
            pass


@pytest.mark.asyncio
async def test_precondition_race_retry(gate):
    gate.fail_once = True
    async with lim.extraction_gate():
        assert gate.generation == 1
    assert gate.generation == 2


@pytest.mark.asyncio
async def test_shutdown_switch(gate, monkeypatch):
    monkeypatch.setattr(settings, "echryn_public_enabled", False)
    with pytest.raises(lim.V1GateError, match="echryn_temporarily_disabled") as err:
        async with lim.extraction_gate():
            pass
    assert err.value.status_code == 503
    assert gate.state is None


@pytest.mark.asyncio
async def test_storage_fail_closed(gate, monkeypatch):
    monkeypatch.setattr(lim, "_blob", lambda: (_ for _ in ()).throw(OSError("storage down")))
    with pytest.raises(lim.V1GateError, match="limiter_unavailable") as err:
        async with lim.extraction_gate():
            pass
    assert err.value.status_code == 503


@pytest.mark.asyncio
async def test_disabled_gate_for_local_development(gate, monkeypatch):
    monkeypatch.setattr(settings, "echryn_v1_limits_enabled", False)
    async with lim.extraction_gate():
        pass
    assert gate.state is None

@pytest.mark.asyncio
async def test_cloud_run_refuses_disabled_limits(gate, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "echryn")
    monkeypatch.setattr(settings, "echryn_v1_limits_enabled", False)
    with pytest.raises(lim.V1GateError, match="public_limits_required") as err:
        async with lim.extraction_gate():
            pass
    assert err.value.status_code == 503
