import asyncio
import json
import threading

import pytest
from odin.adapters.adapter import ApiAdapterRequest
from odin.adapters.parameter_tree import ParameterTreeError

from tristan_detector.control import tristan_adapter
from tristan_detector.control.tristan_adapter import TristanAdapter
from tristan_detector.control.tristan_detector import DetectorTimeoutError


class FakeDetector:
    """Stands in for TristanDetector so the adapter can be tested without hardware"""

    def __init__(self, endpoint, firmware, udp_config_file, update_interval, module):
        self.args = (endpoint, firmware, udp_config_file, update_interval)
        self.module = module
        self.calls = []
        self.shut_down = False
        self.release = threading.Event()

    def get(self, path, meta=False):
        self.calls.append(("get", path, meta))
        if path == "bad":
            raise ParameterTreeError("Invalid path: bad")
        return {path: 1}

    def put(self, path, value):
        self.calls.append(("put", path, value))
        if path == "bad":
            raise ValueError("Unknown path: bad")
        if path == "slow":
            raise DetectorTimeoutError("Time out waiting for detector armed state")
        if path == "block":
            # Wait (as a detector request would) until the test releases it
            assert self.release.wait(5)
        return {"reply": f"reply to {path}"}

    def delete(self, path):
        self.calls.append(("delete", path))
        raise NotImplementedError(f"DELETE {path} is not supported")

    def shutdown(self):
        self.shut_down = True


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(tristan_adapter, "TristanDetector", FakeDetector)
    return TristanAdapter(endpoint="tcp://127.0.0.1:5000", firmware="1.0.0")


def json_request(body="", accept="application/json"):
    return ApiAdapterRequest(body, content_type="application/json", accept=accept)


def test_options_are_passed_to_detector(monkeypatch):
    monkeypatch.setattr(tristan_adapter, "TristanDetector", FakeDetector)
    adapter = TristanAdapter(
        endpoint="tcp://127.0.0.1:5000",
        firmware="1.0.0",
        udp_file="/tmp/udp.json",
        update_interval="2",
    )
    assert isinstance(adapter._controller, FakeDetector)
    assert adapter._controller.args == (
        "tcp://127.0.0.1:5000",
        "1.0.0",
        "/tmp/udp.json",
        2.0,
    )


def test_option_defaults(adapter):
    assert adapter._controller.args == (
        "tcp://127.0.0.1:5000",
        "1.0.0",
        "./udp_tristan.json",
        0.5,
    )


def test_missing_endpoint_raises(monkeypatch):
    monkeypatch.setattr(tristan_adapter, "TristanDetector", FakeDetector)
    with pytest.raises(RuntimeError, match="No endpoint"):
        TristanAdapter(firmware="1.0.0")


def test_get_delegates_to_controller(adapter):
    response = asyncio.run(adapter.get("/status/state/", json_request()))
    assert response.status_code == 200
    assert response.data == {"status/state": 1}
    assert adapter._controller.calls == [("get", "status/state", False)]


def test_get_passes_metadata_flag(adapter):
    asyncio.run(
        adapter.get("status", json_request(accept="application/json;metadata=true"))
    )
    assert adapter._controller.calls == [("get", "status", True)]


def test_get_invalid_path_is_bad_request(adapter):
    response = asyncio.run(adapter.get("bad", json_request()))
    assert response.status_code == 400
    assert "Invalid path" in response.data["error"]


@pytest.mark.parametrize(
    "body, expected",
    [
        ("", None),
        (b"", None),
        (json.dumps({"exposure": 1.5}), {"exposure": 1.5}),
        (json.dumps(2.0).encode(), 2.0),
        ("not json", "not json"),
    ],
)
def test_put_decodes_body(adapter, body, expected):
    response = asyncio.run(adapter.put("config/exposure", json_request(body)))
    assert response.status_code == 200
    assert adapter._controller.calls == [("put", "config/exposure", expected)]


def test_put_native_request_passes_object_through(adapter):
    request = ApiAdapterRequest({"exposure": 1.5})  # odin-native content type
    response = asyncio.run(adapter.put("config", request))
    assert response.status_code == 200
    assert adapter._controller.calls == [("put", "config", {"exposure": 1.5})]


def test_put_error_is_bad_request(adapter):
    response = asyncio.run(adapter.put("bad", json_request("1")))
    assert response.status_code == 400
    assert "Unknown path" in response.data["error"]


def test_delete_is_not_implemented(adapter):
    response = asyncio.run(adapter.delete("config", json_request()))
    assert response.status_code == 501
    assert adapter._controller.calls == [("delete", "config")]


def test_cleanup_shuts_down_controller(adapter):
    asyncio.run(adapter.cleanup())
    assert adapter._controller.shut_down


def test_put_returns_controller_reply(adapter):
    response = asyncio.run(adapter.put("command/arm", json_request()))
    assert response.data == {"reply": "reply to command/arm"}


def test_put_timeout_is_request_timeout(adapter):
    response = asyncio.run(adapter.put("slow", json_request()))
    assert response.status_code == 408
    assert "armed state" in response.data["error"]


def test_adapter_name_is_reported_as_module(adapter):
    assert adapter._controller.module == "TristanAdapter"


def test_get_is_answered_while_a_put_waits_on_the_detector(adapter):
    async def scenario():
        # A PUT that blocks inside the controller, as start_acquisition would
        put = asyncio.create_task(adapter.put("block", json_request()))
        await asyncio.sleep(0.05)
        assert not put.done()
        # The event loop is free, so a GET is answered in the meantime
        response = await asyncio.wait_for(
            adapter.get("status/state", json_request()), timeout=1
        )
        assert response.status_code == 200
        assert not put.done()
        adapter._controller.release.set()
        return await asyncio.wait_for(put, timeout=5)

    put_response = asyncio.run(scenario())
    assert put_response.status_code == 200
