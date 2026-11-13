import time

import pytest

from tristan_detector.control.tristan_channel import TristanChannel
from tristan_detector.control.tristan_detector import TristanDetector, _lookup
from tristan_detector.control.tristan_message import (
    GetMessage,
    ResponseMessage,
    TristanMessage,
)
from tristan_detector.simulator.control_simulator import TristanControlSimulator


@pytest.fixture
def simulator():
    """A control-only simulator bound to a free local port"""
    simulator = TristanControlSimulator(num_events=0)
    simulator.setup_control_channel("tcp://127.0.0.1:*")
    yield simulator
    assert simulator._ctrl_channel is not None
    simulator._ctrl_channel.close()


@pytest.fixture
def client(simulator):
    endpoint = simulator._ctrl_channel.socket.last_endpoint.decode()
    channel = TristanChannel(TristanChannel.CHANNEL_TYPE_DEALER)
    channel.connect(endpoint)
    yield channel
    channel.close()


def request(simulator, client, params):
    """Send a GET to the simulator, run its handler once and return the reply"""
    msg = GetMessage(params=params)
    client.send(msg)
    assert simulator._ctrl_channel.poll(2000), "simulator received nothing"
    simulator.handle_ctrl_msg()
    assert client.poll(2000), "no reply from simulator"
    reply = TristanMessage.parse_json(client.recv())
    assert isinstance(reply, ResponseMessage)
    assert reply.msg_id == msg.msg_id
    return reply.data


def test_control_only_simulator_starts_quickly():
    start = time.monotonic()
    TristanControlSimulator(num_events=0)
    assert time.monotonic() - start < 5


def test_get_full_status(simulator, client):
    status = request(simulator, client, {"status": None})["status"]
    assert status["state"] == "idle"
    assert status["detector"]["x_pixels_in_detector"] == 2048


def test_get_full_config(simulator, client):
    config = request(simulator, client, {"config": None})["config"]
    assert config["mode"] == "time_energy"


def test_default_config_uses_allowed_enum_values(simulator):
    # Guards against the simulator defaults and detector metadata drifting apart
    config = simulator._store["config"]
    for path, allowed_values in TristanDetector.DETECTOR_ENUMS.items():
        assert _lookup(config, path) in allowed_values, path


def test_default_config_has_every_schema_path(simulator):
    # The detector requests every schema path; a missing one fails the whole GET
    config = simulator._store["config"]
    for path in TristanDetector.DETECTOR_CONFIG:
        assert _lookup(config, path) is not None, path
