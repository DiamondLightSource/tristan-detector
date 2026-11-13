"""TristanDetector running against the control simulator over ZeroMQ"""

import json
import threading
import time

import pytest

from tristan_detector.control.control_simulator import TristanControlSimulator
from tristan_detector.control.tristan_detector import TristanDetector


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for condition"
        time.sleep(0.02)


class RunningSimulator:
    def __init__(self):
        self.simulator = TristanControlSimulator(num_events=0)
        self.simulator.setup_control_channel("tcp://127.0.0.1:*")
        channel = self.simulator._ctrl_channel
        assert channel is not None
        self.channel = channel
        self.endpoint = channel.socket.last_endpoint.decode()
        self.thread = threading.Thread(target=self.simulator.start_reactor)
        self.thread.start()
        self.stopped = False

    @property
    def store(self):
        return self.simulator._store

    def stop(self):
        if not self.stopped:
            self.simulator.stop_reactor()
            self.thread.join(timeout=2)
            assert not self.thread.is_alive()
            self.channel.close()
            self.stopped = True


@pytest.fixture
def simulator():
    running = RunningSimulator()
    yield running
    running.stop()


@pytest.fixture
def detector(simulator, tmp_path):
    udp_file = tmp_path / "udp.json"
    udp_file.write_text(json.dumps({"udp": {"dest": "10.0.0.1"}}))
    detector = TristanDetector(simulator.endpoint, "0.0.1", str(udp_file), 0.05)
    yield detector
    detector.shutdown()


def connected(detector):
    return detector.get("status/connected")["value"]


def test_reactor_stops_promptly():
    running = RunningSimulator()
    start = time.monotonic()
    running.stop()
    assert time.monotonic() - start < 1


def test_detector_reads_simulator_status_and_config(detector, simulator):
    wait_for(lambda: connected(detector))
    wait_for(lambda: detector.get("config/mode")["value"] is not None)

    assert detector.get("status/state") == {"value": "idle"}
    detector_status = detector.get("status/detector")["value"]
    assert detector_status["x_pixels_in_detector"] == 2048
    assert detector_status["bytes"] == 2048 * 512 * 2
    assert detector_status["version_check"] is True
    assert detector.get("status/clock/dpll_lol") == {"value": True}
    assert detector.get("status/sensor/temp_asics_1") == {"value": [50.1]}
    assert detector.get("config/mode") == {"value": "time_energy"}
    assert detector.get("config/timeslice/duration_rollover_bits") == {"value": 18}


def test_connecting_sends_time_and_udp_config(detector, simulator):
    default_time = simulator.store["config"]["time"]
    wait_for(lambda: connected(detector))
    wait_for(lambda: "udp" in simulator.store["config"])
    assert simulator.store["config"]["udp"] == {"dest": "10.0.0.1"}
    assert simulator.store["config"]["time"] != default_time


def test_detector_notices_simulator_going_away(detector, simulator):
    wait_for(lambda: connected(detector))
    simulator.stop()
    wait_for(lambda: not connected(detector))
    assert detector.get("status/detector/version_check") == {"value": False}


def test_shutdown_is_prompt(simulator, tmp_path):
    detector = TristanDetector(simulator.endpoint, "0.0.1", "./udp.json", 5.0)
    wait_for(lambda: connected(detector))
    start = time.monotonic()
    detector.shutdown()
    # Without the stop event this would wait out the 5 s update interval
    assert time.monotonic() - start < 1


def test_config_put_reaches_simulator(detector, simulator):
    wait_for(lambda: connected(detector))
    detector.put("config/exposure", 2.5)
    detector.put("config/frames/7", None)
    assert simulator.store["config"]["exposure"] == 2.5
    assert simulator.store["config"]["frames"] == 7
    wait_for(lambda: detector.get("config/exposure") == {"value": 2.5})


def test_engineering_get_returns_simulator_reply(detector, simulator):
    wait_for(lambda: connected(detector))
    response = detector.put("engineering_get", {"exposure": None, "mode": None})
    reply = json.loads(response["reply"])
    assert reply["data"]["config"] == {"exposure": 0.0, "mode": "time_energy"}


def test_start_acquisition_against_simulator(detector, simulator):
    wait_for(lambda: connected(detector))
    detector.put("command/start_acquisition", None)
    assert simulator.store["status"]["state"] == "running"
    assert detector.get("status/acquisition_complete") == {"value": False}
    assert detector.get("status/error") == {"value": ""}
