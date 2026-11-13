import json

import pytest

from tristan_detector.control.tristan_channel import TristanChannel
from tristan_detector.control.tristan_detector import TristanDetector, _lookup
from tristan_detector.control.tristan_message import ResponseMessage

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


STATUS_REPLY = {
    "state": "idle",
    "detector": {
        "software_version": "1.0.0",
        "x_pixels_in_detector": 2048,
        "y_pixels_in_detector": 512,
        "udp_packets_sent": [10, 20, 30],
    },
    "clock": {"dpll_lol": [True], "dpll_hold": [False], "clock_freq": 65.7},
    "sensor": {
        "temp_asics": [[50.0 + i for i in range(16)], [60.0 + i for i in range(16)]],
        "temp_pcb": [[1.0, 2.0], [3.0, 4.0]],
        "humidity": [[5.0, 6.0], [7.0, 8.0]],
    },
    "housekeeping": {"psu_temp": [28.6, 28.7]},
}
CONFIG_REPLY = {"exposure": 1.5, "trigger": {"start": "internal"}}


@pytest.fixture
def link(monkeypatch):
    """Replace detector comms with canned replies, recording the messages sent

    Set ``link.online = False`` to simulate the detector not replying.
    """

    class Link:
        def __init__(self):
            self.online = True
            self.sent = []

        def reply(self, msg):
            self.sent.append((msg.msg_type, msg.params))
            if not self.online:
                return None
            data = {}
            if msg.msg_type == "get" and "status" in msg.params:
                data = {"status": STATUS_REPLY}
            elif msg.msg_type == "get" and "config" in msg.params:
                data = {"config": CONFIG_REPLY}
            return ResponseMessage(msg.msg_id, data)

        def puts(self):
            return [params for msg_type, params in self.sent if msg_type == "put"]

    fake = Link()
    monkeypatch.setattr(TristanDetector, "send_recv", lambda _, msg: fake.reply(msg))
    return fake


@pytest.fixture
def polled(detector, link, tmp_path):
    udp_file = tmp_path / "udp.json"
    udp_file.write_text(json.dumps({"udp": {"dest": "10.0.0.1"}}))
    detector._udp_config_file = str(udp_file)
    return detector


def test_requests_match_main(polled, link):
    polled._poll_detector()
    gets = [params for msg_type, params in link.sent if msg_type == "get"]
    assert gets[0] == {"status": TristanDetector.STATUS_REQUEST}
    # The config request holds a None leaf for every schema path
    config_request = gets[1]["config"]
    assert config_request["exposure"] is None
    assert config_request["trigger"]["timestamp"]["fem"] is None
    for path in TristanDetector.DETECTOR_CONFIG:
        assert _lookup(config_request, path) is None
        assert path.split("/")[0] in config_request


def test_poll_stores_replies(polled):
    assert polled.get("status/connected") == {"connected": False}
    polled._poll_detector()
    assert polled.get("status/connected") == {"connected": True}
    assert polled.get("status/state") == {"state": "idle"}
    assert polled.get("status/housekeeping/psu_temp") == {"psu_temp": [28.6, 28.7]}
    assert polled.get("config/exposure") == {"exposure": 1.5}
    assert polled.get("config/trigger/start") == {"start": "internal"}


def test_derived_status_values(polled):
    polled._poll_detector()
    detector_status = polled.get("status/detector")["detector"]
    assert detector_status["bytes"] == 2048 * 512 * 2
    assert detector_status["version_check"] is True
    assert detector_status["udp_packets_sent"] == 60
    assert polled.get("status/clock") == {
        "clock": {"dpll_lol": True, "dpll_hold": False, "clock_freq": 65.7}
    }
    sensor = polled.get("status/sensor")["sensor"]
    assert sensor["temp_asics_0"] == [50.0, 60.0]
    assert sensor["temp_asics_15"] == [65.0, 75.0]
    assert sensor["temp_pcb_1"] == [2.0, 4.0]
    assert sensor["humidity_0"] == [5.0, 7.0]


def test_derived_values_are_none_before_detector_replies(detector):
    detector_status = detector.get("status/detector")["detector"]
    assert detector_status["bytes"] is None
    assert detector_status["version_check"] is False
    assert detector_status["udp_packets_sent"] is None
    assert detector.get("status/sensor/temp_asics_3") == {"temp_asics_3": None}
    assert detector.get("status/clock/dpll_lol") == {"dpll_lol": None}


def test_version_check_fails_on_firmware_mismatch(polled):
    polled._firmware = "2.0.0"
    polled._poll_detector()
    assert polled.get("status/detector/version_check") == {"version_check": False}


def test_time_and_udp_config_sent_once_per_connection(polled, link):
    polled._poll_detector()
    polled._poll_detector()
    puts = link.puts()
    assert len(puts) == 2
    assert "time" in puts[0]["config"]
    assert puts[1] == {"config": {"udp": {"dest": "10.0.0.1"}}}

    # Lose the detector: disconnected, nothing resent
    link.online = False
    polled._poll_detector()
    assert polled.get("status/connected") == {"connected": False}
    assert polled.get("status/detector/version_check") == {"version_check": False}
    assert len(link.puts()) == 2

    # Reconnect: config is sent again
    link.online = True
    polled._poll_detector()
    assert polled.get("status/connected") == {"connected": True}
    assert len(link.puts()) == 4


def test_acquisition_complete_when_idle(polled):
    polled._acquisition_complete = False
    polled._poll_detector()
    assert polled.get("status/acquisition_complete") == {"acquisition_complete": True}


def test_every_status_path_is_in_tree(detector):
    for path in TristanDetector.OTHER_STATUS_FIELDS:
        detector.get(f"status/{path}")
