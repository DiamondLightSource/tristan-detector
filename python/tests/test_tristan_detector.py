import pytest

from tristan_detector.control.tristan_channel import TristanChannel
from tristan_detector.control.tristan_detector import TristanDetector

# Nothing listens here; the detector must still construct
UNUSED_ENDPOINT = "tcp://127.0.0.1:59999"


@pytest.fixture
def sent(monkeypatch):
    """Record everything sent to the detector instead of sending it"""
    messages = []

    def fake_send(self, data):
        messages.append(data)
        return -1  # as if the detector were unavailable

    monkeypatch.setattr(TristanChannel, "send", fake_send)
    return messages


@pytest.fixture
def detector(monkeypatch, sent):
    # Stop the background thread polling, so tests see only construction behaviour
    monkeypatch.setattr(TristanDetector, "update_loop", lambda self: None)
    detector = TristanDetector(UNUSED_ENDPOINT, "1.0.0", "./udp.json", 0.5)
    yield detector
    detector.shutdown()


def test_construction_does_not_contact_detector(detector, sent):
    assert sent == []


def test_schema_paths_exist_before_detector_replies(detector):
    assert detector.get("status/state") == {"state": None}
    assert detector.get("status/detector/x_pixels_in_detector") == {
        "x_pixels_in_detector": None
    }
    assert detector.get("status/detector/module_dimensions/x_max") == {"x_max": None}
    assert detector.get("config/exposure") == {"exposure": None}
    assert detector.get("config/trigger/timestamp/fem") == {"fem": None}


@pytest.mark.parametrize("meta", [False, True])
def test_every_schema_path_is_in_tree(detector, meta):
    for path in TristanDetector.DETECTOR_STATUS_FIELDS:
        detector.get(f"status/detector/{path}", meta=meta)
    for path in TristanDetector.DETECTOR_CONFIG:
        detector.get(f"config/{path}", meta=meta)


def test_description_is_readable_despite_reserved_name(detector):
    # "description" is a ParameterTree metadata field name
    detector._status = {"detector": {"description": "Tristan 10M"}}
    assert detector.get("status/detector/description") == {"description": "Tristan 10M"}
    response = detector.get("status/detector/description", meta=True)
    assert response["description"]["value"] == "Tristan 10M"


def test_enum_metadata_is_applied(detector):
    response = detector.get("config/trigger/start", meta=True)
    assert (
        response["start"]["allowed_values"]
        == TristanDetector.DETECTOR_ENUMS["trigger/start"]
    )
    assert detector.get("config/mode", meta=True)["mode"]["allowed_values"] == [
        "time_energy",
        "time_only",
        "count",
    ]


def test_leaves_read_latest_store_contents(detector):
    detector._status = {
        "state": "idle",
        "detector": {"x_pixels_in_detector": 4096, "module_dimensions": {"x_max": [7]}},
    }
    detector._config = {"exposure": 1.5, "trigger": {"start": "external_re"}}

    assert detector.get("status/state") == {"state": "idle"}
    assert detector.get("status/detector/x_pixels_in_detector") == {
        "x_pixels_in_detector": 4096
    }
    assert detector.get("status/detector/module_dimensions/x_max") == {"x_max": [7]}
    assert detector.get("config/exposure") == {"exposure": 1.5}
    assert detector.get("config/trigger/start") == {"start": "external_re"}
    # Paths absent from the reply still read as None rather than erroring
    assert detector.get("config/frames") == {"frames": None}


def test_local_fields(detector):
    assert detector.get("firmware") == {"firmware": "1.0.0"}
    assert detector.get("udp_file") == {"udp_file": "./udp.json"}
    assert detector.get("status/manufacturer") == {"manufacturer": "DLS/STFC"}


def test_shutdown_stops_thread_and_closes_channel(monkeypatch, sent):
    closed = []
    real_close = TristanChannel.close

    def recording_close(self):
        closed.append(True)
        real_close(self)

    monkeypatch.setattr(TristanChannel, "close", recording_close)
    detector = TristanDetector(UNUSED_ENDPOINT, "1.0.0", "./udp.json", 0.5)

    detector.shutdown()

    assert not detector._status_thread.is_alive()
    assert closed == [True]
