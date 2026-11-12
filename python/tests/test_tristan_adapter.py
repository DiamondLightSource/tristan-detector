import json

import pytest
from odin.adapters.adapter import ApiAdapterRequest
from odin.adapters.parameter_tree import ParameterTreeError

from tristan_detector.control import tristan_adapter
from tristan_detector.control.tristan_adapter import TristanAdapter


class FakeDetector:
    """Stands in for TristanDetector so the adapter can be tested without hardware"""

    def __init__(self, endpoint, firmware, udp_config_file, update_interval):
        self.args = (endpoint, firmware, udp_config_file, update_interval)
        self.calls = []
        self.shut_down = False

    def get(self, path, meta=False):
        self.calls.append(("get", path, meta))
        if path == "bad":
            raise ParameterTreeError("Invalid path: bad")
        return {path: 1}

    def put(self, path, value):
        self.calls.append(("put", path, value))
        if path == "bad":
            raise ValueError("Unknown path: bad")

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
    response = adapter.get("/status/state/", json_request())
    assert response.status_code == 200
    assert response.data == {"status/state": 1}
    assert adapter._controller.calls == [("get", "status/state", False)]


def test_get_passes_metadata_flag(adapter):
    adapter.get("status", json_request(accept="application/json;metadata=true"))
    assert adapter._controller.calls == [("get", "status", True)]


def test_get_invalid_path_is_bad_request(adapter):
    response = adapter.get("bad", json_request())
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
    response = adapter.put("config/exposure", json_request(body))
    assert response.status_code == 200
    assert adapter._controller.calls == [("put", "config/exposure", expected)]


def test_put_native_request_passes_object_through(adapter):
    request = ApiAdapterRequest({"exposure": 1.5})  # odin-native content type
    response = adapter.put("config", request)
    assert response.status_code == 200
    assert adapter._controller.calls == [("put", "config", {"exposure": 1.5})]


def test_put_error_is_bad_request(adapter):
    response = adapter.put("bad", json_request("1"))
    assert response.status_code == 400
    assert "Unknown path" in response.data["error"]


def test_delete_is_not_implemented(adapter):
    response = adapter.delete("config", json_request())
    assert response.status_code == 501
    assert adapter._controller.calls == [("delete", "config")]


def test_cleanup_shuts_down_controller(adapter):
    adapter.cleanup()
    assert adapter._controller.shut_down
