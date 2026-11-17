"""
Created on 1st November 2017

:author: Alan Greer
"""

import copy
import getpass
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from enum import Enum

from dateutil.tz import tzlocal
from odin.adapters.parameter_tree import ParameterTree, ParameterTreeError

from .tristan_channel import TristanChannel
from .tristan_enums import (
    ModeType,
    ProfileType,
    TriggerClockSourceType,
    TriggerInTerminationType,
    TriggerInType,
    TriggerOutTerminationType,
    TriggerOutType,
    TriggerTimestampType,
    TriggerTZeroType,
)
from .tristan_message import (
    GetMessage,
    PostMessage,
    PutMessage,
    ResponseMessage,
    TristanMessage,
)

logger = logging.getLogger(__name__)


def _lookup(store: dict, path: str):
    """Return the value at a "/"-separated path in a nested dict, or None if absent"""
    node = store
    for key in path.split("/"):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _nest(paths: list[str], leaf: Callable[[str], object]) -> dict:
    """Build a nested dict from "/"-separated paths, with leaf(path) at each leaf"""
    tree: dict = {}
    for path in paths:
        *parents, name = path.split("/")
        node = tree
        for parent in parents:
            node = node.setdefault(parent, {})
        node[name] = leaf(path)
    return tree


def _schema_branch(
    store: Callable[[], dict],
    paths: list[str],
    metadata: dict[str, list[str]] | None = None,
) -> dict:
    """Build a ParameterTree branch with a read-only leaf for each schema path

    Each leaf looks its value up in the dict returned by ``store`` at read time, so
    the branch reflects the latest detector reply without the tree being modified,
    and the store itself may be replaced. Paths missing from the store read as None.

    :param store: callable returning the nested dict holding the values
    :param paths: "/"-separated leaf paths within the store
    :param metadata: optional map of leaf path to its allowed values
    """
    metadata = metadata or {}

    def leaf(path):
        leaf_meta = {"allowed_values": metadata[path]} if path in metadata else {}
        return (lambda: _lookup(store(), path), leaf_meta)

    return _nest(paths, leaf)


def _template_paths(template: dict, prefix: str = "") -> list[str]:
    """List the "/"-separated paths of the leaves of a GET request template"""
    paths = []
    for key, value in template.items():
        if isinstance(value, dict):
            paths += _template_paths(value, f"{prefix}{key}/")
        else:
            paths.append(f"{prefix}{key}")
    return paths


class DetectorTimeoutError(Exception):
    """The detector did not reach an expected state in time"""


class TristanDetector:
    """
    TristanDetector class.
    """

    ADODIN_MAPPING = {
        "config/exposure_time": "config/exposure",
        "config/num_images": "config/frames",
        "status/sensor/width": "status/detector/x_pixels_in_detector",
        "status/sensor/height": "status/detector/y_pixels_in_detector",
        "status/sensor/bytes": "status/detector/bytes",
    }
    # Config parameters polled from the detector and shown in the tree, as on main.
    # readout_time is deliberately absent (main never requested it); PUTs to it
    # are still passed through.
    DETECTOR_CONFIG: dict[str, type[Enum] | None] = {
        # Each path maps to the enum of its allowed values, if it is enumerated
        "exposure": None,
        "frames": None,
        "frames_per_trigger": None,
        "mode": ModeType,
        "ntrigger": None,
        "profile": ProfileType,
        "repeat_interval": None,
        "threshold": None,
        "timeslice/duration_rollover_bits": None,
        "trigger/lvds_out": TriggerOutType,
        "trigger/primary_clock_source": TriggerClockSourceType,
        "trigger/start": TriggerInType,
        "trigger/stop": TriggerInType,
        "trigger/timestamp/fem": TriggerTimestampType,
        "trigger/timestamp/lvds": TriggerTimestampType,
        "trigger/timestamp/sync": TriggerTimestampType,
        "trigger/timestamp/ttl": TriggerTimestampType,
        "trigger/timestamp/tzero": TriggerTimestampType,
        "trigger/ttl_in_term": TriggerInTerminationType,
        "trigger/ttl_out": TriggerOutType,
        "trigger/ttl_out_term": TriggerOutTerminationType,
        "trigger/tzero": TriggerTZeroType,
    }
    STATUS_PATHS = ["status", "config", "command"]
    # Allowed values of each enumerated config parameter, from tristan_enums
    DETECTOR_ENUMS = {
        path: [e.name for e in enum_type]
        for path, enum_type in DETECTOR_CONFIG.items()
        if enum_type is not None
    }

    # Types of numeric config values given in the URL (PUT config/<name>/<value>),
    # as on main
    CONFIG_URL_VALUE_TYPES = {
        "exposure": float,
        "repeat_interval": float,
        "readout_time": float,
        "frames": int,
        "frames_per_trigger": int,
        "ntrigger": int,
        # main converted these with str(float(text)), so "5" is sent as "5.0";
        # non-numeric text is sent unchanged
        "threshold": str,
        "mode": str,
        "profile": str,
    }

    # Status request sent to the detector each poll, as on main (known to work
    # with the hardware)
    STATUS_REQUEST = [
        {
            "state": None,
            "detector": {
                "description": None,
                "detector_type": None,
                "serial_number": None,
                "module_dimensions": {
                    "x_min": [None],
                    "y_min": [None],
                    "x_max": [None],
                    "y_max": [None],
                },
                "software_version": None,
                "software_build": None,
                "sensor_material": None,
                "sensor_thickness": None,
                "x_pixel_size": None,
                "y_pixel_size": None,
                "x_pixels_in_detector": None,
                "y_pixels_in_detector": None,
                "tick_ps": None,
                "tick_hz": None,
                "timeslice_number": None,
                "timing_warning": None,
                "timing_error": None,
                "udp_packets_sent": None,
                "data_overrun": None,
                "frames_acquired": None,
                "shutteropen": None,
                "acquisition_busy": None,
                "shutterbusy": None,
                "fpga_busy": None,
                "loopaction": None,
                "crw": None,
            },
        }
    ]
    # Status fields in the tree from the status request (paths relative to status/)
    STATUS_REQUEST_FIELDS = _template_paths(STATUS_REQUEST[0])
    # Other status fields passed through from the detector reply (paths relative
    # to status/). clock/dpll_* and the split sensor readings are derived.
    OTHER_STATUS_FIELDS = [
        "housekeeping/current_sense",
        "housekeeping/fan_alert",
        "housekeeping/fan_control_temp",
        "housekeeping/fem_power_enabled",
        "housekeeping/output_alert",
        "housekeeping/psu_temp",
        "housekeeping/psu_temp_alert",
        "housekeeping/pwm",
        "housekeeping/remote_temp",
        "housekeeping/standby",
        "housekeeping/tacho",
        "housekeeping/voltage_sense",
        "clock/clock_freq",
        "sensor/current",
        "sensor/humidity",
        "sensor/temp_asics",
        "sensor/temp_pcb",
        "sensor/voltage",
        "fem/temp",
    ]
    # Per-module 2D sensor readings split into one list per channel, as
    # status/sensor/<name>_<channel>
    SENSOR_CHANNELS = {
        "temp_asics": 16,
        "temp_pcb": 2,
        "humidity": 2,
    }
    # Status fields added or replaced from each reply by _process_status, as main
    # did (detector/udp_packets_sent, from the request, is also summed there)
    CALCULATED_STATUS_FIELDS = [
        "detector/bytes",
        "detector/version_check",
        "clock/dpll_lol",
        "clock/dpll_hold",
        *(
            f"sensor/{name}_{index}"
            for name, count in SENSOR_CHANNELS.items()
            for index in range(count)
        ),
    ]
    # Config request sent to the detector each poll: every schema path
    CONFIG_REQUEST = _nest(list(DETECTOR_CONFIG), lambda _: None)
    DETECTOR_TIMEOUT = 1000
    MESSAGE_TYPES = {"get": GetMessage, "put": PutMessage, "post": PostMessage}

    def __init__(
        self,
        endpoint: str,
        firmware: str,
        udp_config_file: str,
        update_interval: float,
        module: str | None = None,
    ):
        """
        :param endpoint: ZeroMQ endpoint of the detector control interface
        :param firmware: expected detector software version, for version_check
        :param udp_config_file: JSON file of UDP config sent on each connection
        :param update_interval: seconds between status and config polls
        :param module: name reported as the module field
        """

        self._endpoint = endpoint
        self._firmware = firmware
        self._udp_config_file = udp_config_file
        self._update_interval = update_interval
        # Reported as the module field; the owning adapter passes its own name
        self._module = module or type(self).__name__
        self._error = ""
        self._start_time = datetime.now()
        self._up_time = ""
        self._username = getpass.getuser()
        self._comms_lock = threading.RLock()

        # Latest status and config replies from the detector. The parameter tree
        # reads from these on every GET; the update loop replaces them on each poll.
        self._status: dict = {"detector": {"version_check": False}}
        self._config: dict = {}
        # Local state maintained by the update loop
        self._connected = False
        self._acquisition_complete = True

        # Create the connection to the hardware
        self._detector = TristanChannel(TristanChannel.CHANNEL_TYPE_DEALER)
        self._detector.connect(self._endpoint)

        # Start with the static/local fields
        _params = {
            "up_time": (lambda: self._up_time, {}),
            "start_time": (
                lambda: self._start_time.strftime("%B %d, %Y %H:%M:%S"),
                {},
            ),
            "username": (lambda: self._username, {}),
            "module": (lambda: self._module, {}),
            "endpoint": (lambda: self._endpoint, {}),
            "firmware": (lambda: self._firmware, {}),
            "udp_file": (lambda: self._udp_config_file, {}),
            "update_interval": (lambda: self._update_interval, {}),
            "status": self._build_status_tree(),
            "config": _schema_branch(
                lambda: self._config,
                list(self.DETECTOR_CONFIG),
                self.DETECTOR_ENUMS,
            ),
        }

        self._params = ParameterTree(_params)

        # Start up the status loop
        self._stop_event = threading.Event()
        self._status_thread = threading.Thread(target=self.update_loop)
        self._status_thread.start()

    def _build_status_tree(self) -> dict:
        """Build the status branch: stored status fields plus local ones"""
        status = _schema_branch(
            lambda: self._status,
            [
                *self.STATUS_REQUEST_FIELDS,
                *self.OTHER_STATUS_FIELDS,
                *self.CALCULATED_STATUS_FIELDS,
            ],
        )
        status.update(
            {
                "manufacturer": (lambda: "DLS/STFC", {}),
                "model": (lambda: "Odin [Tristan]", {}),
                "error": (lambda: self._error, {}),
                "connected": (lambda: self._connected, {}),
                "acquisition_complete": (lambda: self._acquisition_complete, {}),
            }
        )
        return status

    def _process_status(self, reply_status: dict) -> dict:
        """Return a copy of a status reply with main's calculated values added

        As main did after each status poll: the frame size in bytes, the per-module
        UDP packet counts summed, version_check, the first element of each clock
        dpll list, and each per-module 2D sensor reading split into one list per
        channel (e.g. sensor/temp_asics_0). The reply itself is not modified.
        """
        status = copy.deepcopy(reply_status)

        detector = status.setdefault("detector", {})
        x_pixels = detector.get("x_pixels_in_detector")
        y_pixels = detector.get("y_pixels_in_detector")
        if isinstance(x_pixels, int) and isinstance(y_pixels, int):
            detector["bytes"] = x_pixels * y_pixels * 2
        packets = detector.get("udp_packets_sent")
        if isinstance(packets, list):
            detector["udp_packets_sent"] = sum(packets)
        detector["version_check"] = self._firmware == detector.get("software_version")

        clock = status.get("clock", {})
        for name in ("dpll_lol", "dpll_hold"):
            value = clock.get(name)
            if isinstance(value, list) and value:
                clock[name] = value[0]

        sensor = status.get("sensor", {})
        for name, count in self.SENSOR_CHANNELS.items():
            readings = sensor.get(name)
            if not isinstance(readings, list):
                continue
            for index in range(count):
                try:
                    sensor[f"{name}_{index}"] = [module[index] for module in readings]
                except (TypeError, IndexError, KeyError):
                    pass

        return status

    def set_error(self, err: str):
        """Record an error message in status/error and log it"""
        self._error = err
        logger.error(err)

    def clear_error(self):
        """Clear the error message in status/error"""
        self._error = ""

    def shutdown(self):
        """Stop the status update thread and close the detector channel."""
        self._stop_event.set()
        # Allow for an in-progress poll cycle (two detector requests) to time out
        self._status_thread.join(timeout=3 * self.DETECTOR_TIMEOUT / 1000)
        if self._status_thread.is_alive():
            # ZeroMQ sockets are not thread safe, so leave the channel open rather
            # than closing it underneath a thread that may still be using it
            logger.warning("Status update thread did not stop within timeout")
        else:
            self._detector.close()

    def get(self, path, meta=False):
        """Handle GET requests from the controller interface."""
        # Handle empty path — return available endpoints
        if not path:
            return {"status": self.STATUS_PATHS, "config": list(self.DETECTOR_CONFIG)}

        # Handle ADODIN_MAPPING translation
        if path in self.ADODIN_MAPPING:
            path = self.ADODIN_MAPPING[path]

        # ParameterTree reserves "description" as a metadata field name, so without
        # metadata it rejects this path (and omits the leaf from its parent). Serve it
        # directly; with metadata the tree handles it normally.
        if path == "status/detector/description" and not meta:
            result = {"description": _lookup(self._status, "detector/description")}
        else:
            try:
                result = self._params.get(path, with_metadata=meta)
            except ParameterTreeError:
                # As on main, other status paths are looked up in the latest status
                # reply, reading as None if the detector did not send them; any
                # other path outside config (e.g. command/arm) reads as None
                if meta or path.split("/")[0] == "config":
                    raise
                status_path = path.removeprefix("status/")
                if status_path == path:
                    return {"value": None}
                return {"value": _lookup(self._status, status_path)}
            assert isinstance(result, dict)

        # As on main (and as the web UI expects), status and config values are
        # returned as {"value": v}; top-level fields keep their name as the key
        if not meta and path.split("/")[0] in ("status", "config"):
            return {"value": result[path.rsplit("/", 1)[-1]]}
        return result

    def _send(self, msg_type: str, name: str, value):
        """Send a "get", "put" or "post" message with one parameter; return the reply"""
        return self.send_recv(self.MESSAGE_TYPES[msg_type](params={name: value}))

    def put(self, path, value):
        """Handle PUT requests from the controller interface.

        :return: ``{"reply": ...}`` holding the detector's reply as a JSON string,
            or None if it did not reply
        """
        self.clear_error()
        if path in self.ADODIN_MAPPING:
            path = self.ADODIN_MAPPING[path]
        config_items = path.split("/")

        match config_items[0]:
            case "command":
                logger.debug("Command message: %s", config_items[1])
                if path == "command/start_acquisition":
                    return self._arm_then_run()
                elif path == "command/stop_acquisition":
                    # Send a stop command
                    reply = self._send("post", "command", "stop")
                else:
                    reply = self._send("post", "command", config_items[1])

            case "config":
                config = self._config_put_params(path, value)
                logger.info("Config PUT: %s", config)
                reply = self._send("put", "config", config)

            case "engineering" | "engineering_put" | "engineering_get" if (
                len(config_items) == 1
            ):
                # Send an arbitrary JSON object to the hardware as config
                if not isinstance(value, dict):
                    raise ValueError(f"{path} requires a JSON object, got {value!r}")
                logger.debug("Engineering PUT: path=%s, data=%s", path, value)
                # As on main, a bare "engineering" path is a GET
                msg_type = "put" if path == "engineering_put" else "get"
                reply = self._send(msg_type, "config", value)

            case _:
                raise ValueError(f"Unknown path: {path}")

        return {"reply": None if reply is None else str(reply)}

    def delete(self, path):
        """Handle DELETE requests — not supported for this detector."""
        raise NotImplementedError(f"DELETE {path} is not supported")

    def _config_put_params(self, path: str, value) -> dict:
        """Build the config dict to send to the detector for a config PUT

        ``PUT config/a/b`` with value ``v`` gives ``{"a": {"b": v}}``, and ``PUT
        config`` takes a dict value as is. Any path is passed through; the detector
        decides which are valid. With no value (an empty body), the final path
        segment is the value, e.g. ``config/exposure/1.5``, as the web UI sends.

        :raises ValueError: if no value is given or an enum value is not allowed
        """
        if value is None:
            parent, _, text = path.rpartition("/")
            if "/" not in parent:
                raise ValueError(f"No value given for config PUT to {path}")
            path = self.ADODIN_MAPPING.get(parent, parent)
            value = self._parse_url_value(path.rsplit("/", 1)[1], text)
        path = self.ADODIN_MAPPING.get(path, path)

        keys = path.split("/")[1:]
        if not keys and not isinstance(value, dict):
            raise ValueError(f"PUT to config requires an object, got {value!r}")
        config = value
        for key in reversed(keys):
            config = {key: config}
        assert isinstance(config, dict)
        self._check_enum_values(config)
        return config

    def _parse_url_value(self, name: str, text: str):
        """Convert a config value given in the URL, as on main

        Known numeric parameters are converted; other values stay strings.
        """
        value_type = self.CONFIG_URL_VALUE_TYPES.get(name)
        if value_type is None:
            return text
        try:
            return value_type(float(text))
        except ValueError:
            return text

    def _check_enum_values(self, config: dict, prefix: str = ""):
        """Raise ValueError if any enumerated value in ``config`` is not allowed"""
        for key, value in config.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                self._check_enum_values(value, f"{path}/")
            elif path in self.DETECTOR_ENUMS and value not in self.DETECTOR_ENUMS[path]:
                raise ValueError(
                    f"Invalid value {value!r} for config/{path}, allowed values: "
                    + ", ".join(self.DETECTOR_ENUMS[path])
                )

    def _arm_then_run(self):
        """Arm the detector, then run it, waiting for each state as main did

        :raises DetectorTimeoutError: if the detector does not reach a state in time
        """
        logger.info("Starting acquisition sequence")
        self._send("post", "command", "arm")
        self._wait_for_state("armed")

        reply = self._send("post", "command", "run")
        self._wait_for_state("running")

        self._acquisition_complete = False
        logger.info("Acquisition confirmed, setting state to active")
        return {"reply": None if reply is None else str(reply)}

    def _wait_for_state(self, state: str, attempts: int = 50, interval: float = 0.2):
        """Wait for the polled detector state to become ``state``

        :raises DetectorTimeoutError: if it does not within ``attempts * interval``
        """
        logger.info("Waiting for detector %s state", state)
        for _ in range(attempts):
            if _lookup(self._status, "state") == state:
                logger.info("Confirmed %s state", state)
                return
            time.sleep(interval)
        if _lookup(self._status, "state") == state:
            return
        message = f"Time out waiting for detector {state} state"
        self.set_error(message)
        raise DetectorTimeoutError(message)

    def send_udp_config(self):
        """Send the UDP configuration from the udp_file option to the detector"""
        logger.info("Loading UDP configuration from file %s", self._udp_config_file)
        try:
            with open(self._udp_config_file) as config_file:
                udp_config = json.load(config_file)
        except OSError as io_error:
            self.set_error(f"Failed to open UDP configuration file: {io_error}")
            return
        except ValueError as value_error:
            self.set_error(f"Failed to parse UDP json config: {value_error}")
            return

        logger.info("Downloading UDP configuration: %s", udp_config)
        reply = self._send("put", "config", udp_config)
        logger.info("Reply from message: %s", reply)

    def send_recv(self, msg):
        """Send a message and wait for the reply with the same msg_id

        :return: the reply, or None if the detector did not reply in time
        """
        logger.debug("Message Request: %s", msg)
        reply = None
        with self._comms_lock:
            status = self._detector.send(msg)

            if status > -1:
                pollevts = self._detector.poll(self.DETECTOR_TIMEOUT)
                if pollevts == TristanChannel.POLLIN:
                    reply = TristanMessage.parse_json(self._detector.recv())

                # Continue attempting to get the correct reply until timeout
                while reply and reply.msg_id != msg.msg_id:
                    reply = None
                    pollevts = self._detector.poll(self.DETECTOR_TIMEOUT)
                    if pollevts == TristanChannel.POLLIN:
                        reply = TristanMessage.parse_json(self._detector.recv())

        logger.debug("Reply: %s", reply)
        return reply

    def update_loop(self):
        """Poll the detector status and config every update interval until shutdown

        Each poll replaces the stored status and config replies, which the parameter
        tree reads from; the tree itself is never modified.
        """
        next_poll = time.monotonic()
        while not self._stop_event.wait(max(0.0, next_poll - time.monotonic())):
            next_poll = time.monotonic() + self._update_interval
            try:
                self._poll_detector()
            except Exception:
                logger.exception("Error polling detector")

    def _poll_detector(self):
        """Request status and config from the detector and store the replies"""
        self._up_time = str(datetime.now() - self._start_time)

        reply = self._send("get", "status", self.STATUS_REQUEST)
        if not isinstance(reply, ResponseMessage):
            if self._connected:
                logger.warning("Lost connection to detector at %s", self._endpoint)
                # As on main, version_check is false while disconnected; the rest
                # of the last status is kept
                detector = {**self._status.get("detector", {}), "version_check": False}
                self._status = {**self._status, "detector": detector}
            self._connected = False
            return

        logger.debug("Status reply: %s", reply)
        self._status = self._process_status(reply.data["status"])
        if not self._connected:
            logger.info("Connected to detector at %s", self._endpoint)
            self._on_connect()
            self._connected = True
        if self._status.get("state") == "idle":
            self._acquisition_complete = True

        reply = self._send("get", "config", self.CONFIG_REQUEST)
        if isinstance(reply, ResponseMessage):
            logger.debug("Config reply: %s", reply)
            self._config = reply.data["config"]

    def _on_connect(self):
        """Send the time and UDP configuration to a newly (re)connected detector"""
        connect_time = datetime.now(tzlocal()).strftime("%Y-%m-%dT%H:%M%z")
        self._send("put", "config", {"time": connect_time})
        self.send_udp_config()
