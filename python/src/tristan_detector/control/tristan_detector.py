"""
Created on 1st November 2017

:author: Alan Greer
"""

import getpass
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from enum import Enum

from dateutil.tz import tzlocal
from odin.adapters.parameter_tree import ParameterTree
from odin_data.control.odin_data_controller import OdinDataController

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

# Enum type of each enumerated config parameter (paths relative to config/)
CONFIG_ENUM_TYPES: dict[str, type[Enum]] = {
    "mode": ModeType,
    "profile": ProfileType,
    "trigger/start": TriggerInType,
    "trigger/stop": TriggerInType,
    "trigger/timestamp/fem": TriggerTimestampType,
    "trigger/timestamp/lvds": TriggerTimestampType,
    "trigger/timestamp/sync": TriggerTimestampType,
    "trigger/timestamp/ttl": TriggerTimestampType,
    "trigger/timestamp/tzero": TriggerTimestampType,
    "trigger/ttl_in_term": TriggerInTerminationType,
    "trigger/ttl_out_term": TriggerOutTerminationType,
    "trigger/primary_clock_source": TriggerClockSourceType,
    "trigger/tzero": TriggerTZeroType,
    "trigger/ttl_out": TriggerOutType,
    "trigger/lvds_out": TriggerOutType,
}


def _lookup(store: dict, path: str):
    """Return the value at a "/"-separated path in a nested dict, or None if absent"""
    node = store
    for key in path.split("/"):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _schema_branch(
    store: Callable[[], dict],
    prefix: str,
    paths: list[str],
    metadata: dict[str, list[str]] | None = None,
) -> dict:
    """Build a ParameterTree branch with a read-only leaf for each schema path

    Each leaf looks its value up in the dict returned by ``store`` at read time, so
    the branch reflects the latest detector reply without the tree being modified,
    and the store itself may be replaced. Paths missing from the store read as None.

    :param store: callable returning the nested dict holding the values
    :param prefix: path of this branch within the store ("" for the store root)
    :param paths: "/"-separated leaf paths relative to the branch
    :param metadata: optional map of leaf path to its allowed values
    """
    metadata = metadata or {}
    branch: dict = {}
    for path in paths:
        *parents, leaf = path.split("/")
        node = branch
        for parent in parents:
            node = node.setdefault(parent, {})
        store_path = f"{prefix}/{path}" if prefix else path
        leaf_meta = {"allowed_values": metadata[path]} if path in metadata else {}
        node[leaf] = (lambda p=store_path: _lookup(store(), p), leaf_meta)
    return branch


def _request_template(paths: list[str]) -> dict:
    """Build a GET request template, with a None leaf for each "/"-separated path"""
    template: dict = {}
    for path in paths:
        *parents, leaf = path.split("/")
        node = template
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = None
    return template


def _first(value):
    """The first element of a list value; other values are returned unchanged"""
    return value[0] if isinstance(value, list) and value else value


def _column(value, index: int):
    """Element ``index`` of each per-module list in a 2D list value, or None"""
    try:
        return [module[index] for module in value]
    except (TypeError, IndexError, KeyError):
        return None


class DetectorTimeoutError(Exception):
    """The detector did not reach an expected state in time"""


class TristanDetector(OdinDataController):
    """
    TristanDetector class.
    """

    STR_API = "api"
    STR_DETECTOR = "detector"
    STR_FW = "filewriter"
    STR_CONFIG = "config"
    STR_STATUS = "status"
    STR_COMMAND = "command"

    TEMP_ASICS_COUNT = 16
    TEMP_PCB_COUNT = 2
    HUMIDITY_COUNT = 2

    ADODIN_MAPPING = {
        "config/exposure_time": "config/exposure",
        "config/num_images": "config/frames",
        "status/sensor/width": "status/detector/x_pixels_in_detector",
        "status/sensor/height": "status/detector/y_pixels_in_detector",
        "status/sensor/bytes": "status/detector/bytes",
    }
    DETECTOR_CONFIG = [
        "exposure",
        "frames",
        "frames_per_trigger",
        "mode",
        "ntrigger",
        "profile",
        "readout_time",
        "repeat_interval",
        "threshold",
        "timeslice/duration_rollover_bits",
        "trigger/lvds_out",
        "trigger/primary_clock_source",
        "trigger/start",
        "trigger/stop",
        "trigger/timestamp/fem",
        "trigger/timestamp/lvds",
        "trigger/timestamp/sync",
        "trigger/timestamp/ttl",
        "trigger/timestamp/tzero",
        "trigger/ttl_in_term",
        "trigger/ttl_out",
        "trigger/ttl_out_term",
        "trigger/tzero",
    ]
    STATUS_PATHS = ["status", "config", "command"]
    # Allowed values of each enumerated config parameter, from tristan_enums
    DETECTOR_ENUMS = {
        path: [e.name for e in enum_type]
        for path, enum_type in CONFIG_ENUM_TYPES.items()
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
    }

    CORE_STATUS_LIST = {
        "manufacturer": "DLS/STFC",
        "model": "Odin [Tristan]",
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
    # Fields of status/detector passed through from the detector reply.
    # udp_packets_sent, bytes and version_check are derived (see __init__).
    DETECTOR_STATUS_FIELDS = [
        "acquisition_busy",
        "crw",
        "data_overrun",
        "description",
        "detector_type",
        "fpga_busy",
        "frames_acquired",
        "loopaction",
        "module_dimensions/x_max",
        "module_dimensions/x_min",
        "module_dimensions/y_max",
        "module_dimensions/y_min",
        "shutterbusy",
        "shutteropen",
        "sensor_material",
        "sensor_thickness",
        "serial_number",
        "software_build",
        "software_version",
        "tick_hz",
        "tick_ps",
        "timeslice_number",
        "timing_error",
        "timing_warning",
        "x_max",
        "x_min",
        "x_pixel_size",
        "x_pixels_in_detector",
        "y_max",
        "y_min",
        "y_pixel_size",
        "y_pixels_in_detector",
    ]
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
        "temp_asics": TEMP_ASICS_COUNT,
        "temp_pcb": TEMP_PCB_COUNT,
        "humidity": HUMIDITY_COUNT,
    }
    # Config request sent to the detector each poll: every schema path
    CONFIG_REQUEST = _request_template(DETECTOR_CONFIG)
    DETECTOR_TIMEOUT = 1000
    ERROR_NO_RESPONSE = "No response from client, check it is running"
    ERROR_FAILED_TO_SEND = "Unable to successfully send request to client"
    ERROR_FAILED_GET = "Unable to successfully complete the GET request"
    ERROR_PUT_MISMATCH = (
        "The size of parameter array does not match the number of clients"
    )

    def __init__(
        self,
        endpoint: str,
        firmware: str,
        udp_config_file: str,
        update_interval: float,
        module: str | None = None,
    ):
        """
        Initialise the TristanDetector object.
        """

        self._endpoint = endpoint or None
        self._firmware = firmware
        self._udp_config_file = udp_config_file
        self._update_interval = update_interval
        # Reported as the module field; the owning adapter passes its own name
        self._module = module or type(self).__name__
        self._error = ""
        self._armed = False
        self._start_time = datetime.now()
        self._up_time = ""
        self._username = getpass.getuser()
        self._comms_lock = threading.RLock()

        # Latest status and config replies from the detector. The parameter tree
        # reads from these on every GET; the update loop replaces them on each poll.
        self._status: dict = {}
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
            self.STR_STATUS: self._build_status_tree(),
            self.STR_CONFIG: _schema_branch(
                lambda: self._config, "", self.DETECTOR_CONFIG, self.DETECTOR_ENUMS
            ),
            self.STR_COMMAND: {
                "arm": (
                    lambda: 0,
                    lambda v: self.send_recv(PostMessage(params={"command": "arm"})),
                    {},
                ),
                "run": (
                    lambda: 0,
                    lambda v: self.send_recv(PostMessage(params={"command": "run"})),
                    {},
                ),
                "stop": (
                    lambda: 0,
                    lambda v: self.send_recv(PostMessage(params={"command": "stop"})),
                    {},
                ),
                "trigger": (
                    lambda: 0,
                    lambda v: self.send_recv(
                        PostMessage(params={"command": "trigger"})
                    ),
                    {},
                ),
                "cancel": (
                    lambda: 0,
                    lambda v: self.send_recv(PostMessage(params={"command": "cancel"})),
                    {},
                ),
                "abort": (
                    lambda: 0,
                    lambda v: self.send_recv(PostMessage(params={"command": "abort"})),
                    {},
                ),
                "disarm": (
                    lambda: 0,
                    lambda v: self.send_recv(PostMessage(params={"command": "disarm"})),
                    {},
                ),
            },
        }

        self._params = ParameterTree(_params)

        # Start up the status loop
        self._stop_event = threading.Event()
        self._status_thread = threading.Thread(target=self.update_loop)
        self._status_thread.start()

    def _build_status_tree(self) -> dict:
        """Build the status branch: detector reply fields plus local/derived ones"""
        status = _schema_branch(
            lambda: self._status,
            "",
            [
                "state",
                *(f"detector/{path}" for path in self.DETECTOR_STATUS_FIELDS),
                *self.OTHER_STATUS_FIELDS,
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
        status["detector"].update(
            {
                "bytes": (self._detector_bytes, {}),
                "version_check": (self._version_check, {}),
                "udp_packets_sent": (self._udp_packets_sent, {}),
            }
        )
        for name in ("dpll_lol", "dpll_hold"):
            status["clock"][name] = (
                lambda n=name: _first(_lookup(self._status, f"clock/{n}")),
                {},
            )
        for name, count in self.SENSOR_CHANNELS.items():
            for index in range(count):
                status["sensor"][f"{name}_{index}"] = (
                    lambda n=name, i=index: _column(
                        _lookup(self._status, f"sensor/{n}"), i
                    ),
                    {},
                )
        return status

    def _detector_bytes(self):
        """Size of a full detector frame in bytes (2 bytes per pixel)"""
        x_pixels = _lookup(self._status, "detector/x_pixels_in_detector")
        y_pixels = _lookup(self._status, "detector/y_pixels_in_detector")
        if isinstance(x_pixels, int) and isinstance(y_pixels, int):
            return x_pixels * y_pixels * 2
        return None

    def _version_check(self):
        """Whether the connected detector runs the expected firmware version"""
        return self._connected and self._firmware == _lookup(
            self._status, "detector/software_version"
        )

    def _udp_packets_sent(self):
        """Total UDP packets sent, summed over the per-module counts"""
        packets = _lookup(self._status, "detector/udp_packets_sent")
        if isinstance(packets, list):
            return sum(packets)
        return packets

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
            return {"status": self.STATUS_PATHS, "config": self.DETECTOR_CONFIG}

        # Handle ADODIN_MAPPING translation
        if path in self.ADODIN_MAPPING:
            path = self.ADODIN_MAPPING[path]

        # ParameterTree reserves "description" as a metadata field name, so without
        # metadata it rejects this path (and omits the leaf from its parent). Serve it
        # directly; with metadata the tree handles it normally.
        if path == "status/detector/description" and not meta:
            result = {"description": _lookup(self._status, "detector/description")}
        else:
            result = self._params.get(path, with_metadata=meta)
            assert isinstance(result, dict)

        # As on main (and as the web UI expects), status and config values are
        # returned as {"value": v}; top-level fields keep their name as the key
        if not meta and path.split("/")[0] in (self.STR_STATUS, self.STR_CONFIG):
            return {"value": result[path.rsplit("/", 1)[-1]]}
        return result

    def _send(self, cmd_type: str, cmd: str, value: str | int | float | dict | list):
        match cmd_type:
            case "put":
                msg = PutMessage()
            case "post":
                msg = PostMessage()
            case "get":
                msg = GetMessage()
            case _:
                raise AssertionError(f"{cmd_type} is not a valid command type")

        msg.set_param(cmd, value)
        reply = self.send_recv(msg)

        return reply

    # Returns the reply rather than None as OdinDataController.put does; that base
    # implementation is not used
    def put(self, path, value):  # pyright: ignore[reportIncompatibleMethodOverride]
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

            case "engineering_put" | "engineering_get" if len(config_items) == 1:
                # Send an arbitrary JSON object to the hardware as config
                if not isinstance(value, dict):
                    raise ValueError(f"{path} requires a JSON object, got {value!r}")
                logger.debug("Engineering PUT: path=%s, data=%s", path, value)
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
        response = {}

        # Send an arm command
        logger.info("Starting acquisition sequence")
        reply = self._send("post", "command", "arm")

        counter = 0
        # Wait for the status to become armed
        logger.info("Arm command sent, waiting for armed response")
        while _lookup(self._status, "state") != "armed" and counter < 50:
            time.sleep(0.2)
            counter += 1

        # Check for a timeout and if there is raise an error
        if _lookup(self._status, "state") != "armed":
            self.set_error("Time out waiting for detector armed state")
            raise DetectorTimeoutError("Time out waiting for detector armed state")
        else:
            logger.info("Confirmed armed response")
            # Detector armed OK, now tell it to run
            # Send a run command
            with self._comms_lock:
                reply = self._send("post", "command", "run")

            counter = 0
            # Wait for the status to become running
            logger.info("Run command sent, waiting for running response")
            while _lookup(self._status, "state") != "running" and counter < 50:
                time.sleep(0.2)
                counter += 1
            # Check for a timeout and if there is raise an error
            if _lookup(self._status, "state") != "running":
                self.set_error("Time out waiting for detector running state")
                raise DetectorTimeoutError(
                    "Time out waiting for detector running state"
                )

            else:
                logger.info("Confirmed running response")
                with self._comms_lock:
                    # Once the reply has been received, set the
                    # acquisition status to active
                    self._acquisition_complete = False
                    logger.info("Acquisition confirmed, setting state to active")
            response["reply"] = None if reply is None else str(reply)
        return response

    def send_udp_config(self):
        """
        Send the specified udp configuration to the detector
        :param self:
        :return:
        """
        # Load the spcified file into a JSON object
        logger.info(f"Loading UDP configuration from file {self._udp_config_file}")
        try:
            with open(self._udp_config_file) as config_file:
                udp_config = json.load(config_file)
        except OSError as io_error:
            logger.error(f"Failed to open UDP configuration file: {io_error}")
            self.set_error(f"Failed to open UDP configuration file: {io_error}")
            return
        except ValueError as value_error:
            logger.error(f"Failed to parse UDP json config: {value_error}")
            self.set_error(f"Failed to parse UDP json config: {value_error}")
            return

        logger.info(f"Downloading UDP configuration: {udp_config}")
        reply = self._send("put", "config", udp_config)
        logger.info(f"Reply from message: {reply}")

    def send_recv(self, msg):
        """
        Send a message and wait for the response
        :param self:
        :param msg:
        :return:
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
            self._connected = False
            return

        logger.debug("Status reply: %s", reply)
        self._status = reply.data["status"]
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
