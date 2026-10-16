"""
Created on 1st November 2017

:author: Alan Greer
"""

import getpass
import json
import logging
import threading
import time
from datetime import datetime
from typing import cast

from dateutil.tz import tzlocal
from odin.adapters.parameter_tree import ParameterTree
from odin_data.control.odin_data_controller import OdinDataController

from .latrd_channel import LATRDChannel
from .latrd_message import GetMessage, LATRDMessage, PostMessage, PutMessage

logger = logging.getLogger(__name__)


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
    DETECTOR_ENUMS = {
        "mode": ["time_energy", "time_only", "count"],
        "profile": ["standard", "fast", "energy", "user", "current"],
        "trigger/start": [
            "internal",
            "external_re",
            "external_fe",
            "external_lvds_re",
            "external_lvds_fe",
        ],
        "trigger/stop": [
            "internal",
            "external_re",
            "external_fe",
            "external_lvds_re",
            "external_lvds_fe",
        ],
        "trigger/timestamp/fem": ["none", "re", "fe", "both"],
        "trigger/timestamp/lvds": ["none", "re", "fe", "both"],
        "trigger/timestamp/sync": ["none", "re", "fe", "both"],
        "trigger/timestamp/ttl": ["none", "re", "fe", "both"],
        "trigger/timestamp/tzero": ["none", "re", "fe", "both"],
        "trigger/ttl_in_term": ["term_50ohm", "hi_z"],
        "trigger/ttl_out_term": ["term_50ohm", "lo_z"],
        "trigger/primary_clock_source": ["internal", "external"],
        "trigger/tzero": ["internal", "external", "off"],
        "trigger/ttl_out": [
            "follow_shutter",
            "follow_shutter_read",
            "one_per_acq_burst",
            "busy",
            "counter_select",
            "tzero",
            "sync",
            "lvds",
            "ttl",
        ],
        "trigger/lvds_out": [
            "follow_shutter",
            "follow_shutter_read",
            "one_per_acq_burst",
            "busy",
            "counter_select",
            "tzero",
            "sync",
            "lvds",
            "ttl",
        ],
    }

    CORE_STATUS_LIST = {
        "manufacturer": "DLS/STFC",
        "model": "Odin [Tristan]",
    }
    DETECTOR_STATUS = ["state", "error"]
    DETECTOR_STATUS_FIELDS = [
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
        "udp_packets_sent",
        "x_max",
        "x_min",
        "x_pixel_size",
        "x_pixels_in_detector",
        "y_max",
        "y_min",
        "y_pixel_size",
        "y_pixels_in_detector",
    ]
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
        api_version: str,
        firmware: str,
        udp_config_file: str,
        update_interval: float,
    ):
        """
        Initialise the TristanDetector object.
        """

        self._endpoint = endpoint or None
        self._api_version = api_version
        self._firmware = firmware
        self._udp_config_file = udp_config_file
        self._update_interval = update_interval
        self._error = ""
        self._armed = False
        self._start_time = datetime.now()
        self._up_time = ""
        self._username = getpass.getuser()
        self._comms_lock = threading.RLock()

        # Create the connection to the hardware
        self._detector = LATRDChannel(LATRDChannel.CHANNEL_TYPE_DEALER)
        self._detector.connect(self._endpoint)

        # Start with the static/local fields
        _params = {
            "up_time": (lambda: self._up_time, {}),
            "start_time": (
                lambda: self._start_time.strftime("%B %d, %Y %H:%M:%S"),
                {},
            ),
            "username": (lambda: self._username, {}),
            "module": (lambda: type(self).__name__, {}),
            "firmware": (lambda: self._firmware, {}),
            "udp_file": (lambda: self._udp_config_file, {}),
            "update_interval": (lambda: self._update_interval, {}),
            self.STR_STATUS: {
                "manufacturer": (lambda: "DLS/STFC", {}),
                "model": (lambda: "Odin [Tristan]", {}),
                "error": (lambda: "", {}),
                "connected": (lambda: False, {}),
                "acquisition_complete": (lambda: True, {}),
                "state": None,  # placeholder, filled by status loop
                "detector": {},
            },
            self.STR_CONFIG: {},
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

        # Walk the status response to fill the tree
        def _build__params(node: dict, response_data: dict, path_prefix=""):
            for key, value in response_data.items():
                full_path = f"{path_prefix}/{key}" if path_prefix else key
                if isinstance(value, dict):
                    if key not in node:
                        node[key] = {}
                    _build__params(node[key], value, full_path)
                else:
                    metadata = {}
                    if full_path in self.DETECTOR_ENUMS:
                        metadata["allowed_values"] = self.DETECTOR_ENUMS[full_path]
                    node[key] = (
                        lambda v=value: self.get_value(v),
                        metadata,
                    )

        status_reply = self.send_recv("status")
        if status_reply:
            _build__params(
                _params["status"]["detector"], status_reply["status"]["detector"]
            )

        config_reply = self.send_recv("config")
        if config_reply:
            _build__params(_params["config"], config_reply["config"])

        self._params = ParameterTree(_params)

        # Start up the status loop
        self._status_running = True
        self._update_time = datetime.now()
        self._status_thread = threading.Thread(target=self.update_loop)
        self._status_thread.start()

    def get(self, path, meta=False):
        """Handle GET requests from the controller interface."""
        # Handle empty path — return available endpoints
        if not path:
            return {"status": self.STATUS_PATHS, "config": self.DETECTOR_CONFIG}

        # Handle ADODIN_MAPPING translation
        if path in self.ADODIN_MAPPING:
            path = self.ADODIN_MAPPING[path]

        # Return from parameter tree
        return self._params.get(path, with_metadata=meta)

    def get_value(self, item):
        # Check if the item has a value field. If it does then return it
        if isinstance(item, dict) and "value" in item:
            return item["value"]
        return None

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

    def put(self, path, value):
        """Handle PUT requests from the controller interface."""
        self.clear_error()
        if path in self.ADODIN_MAPPING:
            path = self.ADODIN_MAPPING[path]
        config_items = path.split("/")

        match config_items[0]:
            case "command":
                logger.debug("Command message: %s", config_items[1])
                if path == "command/start_acquisition":
                    self._arm_then_run()
                elif path == "command/stop_acquisition":
                    # Send a stop command
                    self._send("post", "command", "stop")
                else:
                    self._send("post", "command", config_items[1])

            case "config":
                command, value_dict = self._parse_config_put(path, value)
                logger.info("Config command: %s", command)
                logger.info("Config dict: %s", value_dict)
                self._send("put", command, value_dict)

            case "engineering":
                # This special command allows an arbitrary JSON object to be
                # sent to the hardware
                logger.debug("Engineering PUT: path=%s, data=%s", path, value)
                msg_type = "put" if "engineering_put" in config_items[0] else "get"
                self._send(msg_type, "config", value)

            case _:
                raise ValueError(f"Unknown path: {path}")

    def delete(self, path):
        """Handle DELETE requests — not supported for this detector."""
        raise NotImplementedError(f"DELETE {path} is not supported")

    def _parse_config_put(self, path, data):
        """Parse a config PUT request into command and value dict."""
        if data is None:
            return path, {}
        if isinstance(data, dict):
            return path, data
        # Simple value — wrap in the path structure
        return path, {"value": data}

    def _arm_then_run(self):
        # status_code = 200
        response = {}

        # Send an arm command
        logger.info("Starting acquisition sequence")
        reply = self._send("post", "command", "arm")

        counter = 0
        # Wait for the status to become armed
        logger.info("Arm command sent, waiting for armed response")
        while self._params.get("status/state") != "armed" and counter < 50:
            time.sleep(0.2)
            counter += 1

        # Check for a timeout and if there is raise an error
        if self._params.get("status/state") != "armed":
            self.set_error("Time out waiting for detector armed state")
            # status_code = 408
            response["reply"] = "Time out waiting for detector armed state"
        else:
            logger.info("Confirmed armed response")
            # Detector armed OK, now tell it to run
            # Send a run command
            with self._comms_lock:
                reply = self._send("post", "command", "run")

            counter = 0
            # Wait for the status to become running
            logger.info("Run command sent, waiting for running response")
            while self._params.get("status/state") != "running" and counter < 50:
                time.sleep(0.2)
                counter += 1
            # Check for a timeout and if there is raise an error
            if self._params.get("status/state") != "running":
                self.set_error("Time out waiting for detector running state")
                # status_code = 408
                response["reply"] = "Time out waiting for detector running state"

            else:
                logger.info("Confirmed running response")
                with self._comms_lock:
                    # Once the reply has been received, set the
                    # acquisition status to active
                    self._params.set("status/acquisition_complete", False)
                    logger.info("Acquisition confirmed, setting state to active")
            response["reply"] = str(reply)

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
                if pollevts == LATRDChannel.POLLIN:
                    reply = LATRDMessage.parse_json(self._detector.recv())

                # Continue attempting to get the correct reply until timeout
                while reply and reply.msg_id != msg.msg_id:
                    reply = None
                    pollevts = self._detector.poll(self.DETECTOR_TIMEOUT)
                    if pollevts == LATRDChannel.POLLIN:
                        reply = LATRDMessage.parse_json(self._detector.recv())

        logger.debug("Reply: %s", reply)
        return reply

    def update_loop(self):
        """Handle background update loop tasks.
        This method handles background update tasks executed periodically in a thread
        This includes requesting the status from the underlying application
        and preparing the JSON encoded reply in a format that can be easily parsed.
        """
        while self._status_running:
            time.sleep(0.1)
            if (
                float((datetime.now() - self._update_time).seconds)
                > self._update_interval
            ):
                self._update_time = datetime.now()
                try:
                    with self._comms_lock:
                        logger.debug("Updating status from detector...")
                        # Update server uptime
                        self._up_time = str(datetime.now() - self._start_time)

                        reply = self._send("get", "status", [self.DETECTOR_STATUS])

                        if reply is not None:
                            logger.debug("Raw reply: %s", reply)
                            if LATRDMessage.MSG_TYPE_RESPONSE in reply.msg_type:
                                data: dict = reply["data"]
                                currently_connected = self._params.get(
                                    "status/connected"
                                )
                                self._params.set("status", data["status"])

                                # Perform post status manipulation
                                if "detector" in self._params.get("status"):
                                    if "x_pixels_in_detector" in self._params.get(
                                        "status/detector"
                                    ) and "y_pixels_in_detector" in self._params.get(
                                        "status/detector"
                                    ):
                                        x_pixels = self._params.get(
                                            "status/detector/x_pixels_in_detector"
                                        )
                                        assert isinstance(x_pixels, int)
                                        y_pixels = self._params.get(
                                            "status/detector/y_pixels_in_detector"
                                        )
                                        assert isinstance(y_pixels, int)
                                        self._params.set(
                                            "status/detector/bytes",
                                            x_pixels * y_pixels * 2,
                                        )
                                    # Sum the packets sent from the detector (by module)
                                    # into a single total
                                    if "udp_packets_sent" in self._params.get(
                                        "status/detector"
                                    ):
                                        pckts = self._params.get(
                                            "status/detector/udp_packets_sent"
                                        )
                                        if isinstance(pckts, list):
                                            self._params.set(
                                                "status/detector/udp_packets_sent",
                                                len(pckts),
                                            )
                                # Check if we just reconnected
                                if not currently_connected:
                                    # Send timestamp config on reconnection
                                    connect_time = datetime.now(tzlocal()).strftime(
                                        "%Y-%m-%dT%H:%M%z"
                                    )
                                    reply = self._send(
                                        "put", "config", {"time": connect_time}
                                    )
                                    # Resend the UDP configuration on re-connection
                                    self.send_udp_config()

                                # Now set the connection status to True
                                self._params.set("status/connected", True)
                                if self._firmware == self._params.get(
                                    "status/detector/software_version"
                                ):
                                    self._params.set(
                                        "status/detector/version_check", True
                                    )
                                else:
                                    self._params.set(
                                        "status/detector/version_check", False
                                    )

                                try:
                                    if "clock" in self._params.get("status"):
                                        if "dpll_lol" in self._params.get(
                                            "status/clock"
                                        ):
                                            self._params.set(
                                                "status/clock/dpll_lol",
                                                self._params.get(
                                                    "status/clock/dpll_lol"
                                                )[0],
                                            )
                                        if "dpll_hold" in self._params.get(
                                            "status/clock"
                                        ):
                                            self._params.set(
                                                "status/clock/dpll_hold",
                                                self._params.get(
                                                    "status/clock/dpll_hold"
                                                )[0],
                                            )
                                except Exception as ex:
                                    logger.error("Error reading clock status items", ex)
                                    logger.error("Exception: %s", ex)

                                if "sensor" in self._params.get("status"):
                                    if "temp_asics" in self._params.get(
                                        "status/sensor"
                                    ):
                                        # temp_asics is 2D; split for monitoring
                                        for index in range(self.TEMP_ASICS_COUNT):
                                            self._params.set(
                                                f"status/sensor/temp_asics_{index}", []
                                            )
                                            for temp in self._params.get(
                                                "status/sensor/temp_asics"
                                            ):
                                                current = cast(
                                                    dict,
                                                    self._params.get(
                                                        f"status/sensor/temp_asics_{index}"
                                                    ),
                                                )
                                                cast(list, current["value"]).append(
                                                    temp[index]
                                                )
                                                current = self._params.set(
                                                    f"status/sensor/temp_asics_{index}",
                                                    current,
                                                )

                                    if "temp_pcb" in self._params.get("status/sensor"):
                                        # temp_pcb is 2D; split for monitoring
                                        for index in range(self.TEMP_PCB_COUNT):
                                            self._params.set(
                                                f"status/sensor/temp_pcb_{index}", []
                                            )
                                            for temp in self._params.get(
                                                "status/sensor/temp_pcb"
                                            ):
                                                current = cast(
                                                    dict,
                                                    self._params.get(
                                                        f"status/sensor/temp_pcb_{index}"
                                                    ),
                                                )
                                                cast(list, current["value"]).append(
                                                    temp[index]
                                                )
                                                self._params.set(
                                                    f"status/sensor/temp_pcb_{index}",
                                                    current,
                                                )

                                    if "humidity" in self._params.get("status/sensor"):
                                        # humidity is 2D; split for monitoring
                                        for index in range(self.HUMIDITY_COUNT):
                                            self._params.set(
                                                f"status/sensor/humidity_{index}", []
                                            )
                                            for temp in self._params.get(
                                                "status/sensor/humidity"
                                            ):
                                                current = cast(
                                                    dict,
                                                    self._params.get(
                                                        f"status/sensor/humidity_{index}"
                                                    ),
                                                )
                                                cast(list, current["value"]).append(
                                                    temp[index]
                                                )
                                                self._params.set(
                                                    f"status/sensor/humidity_{index}",
                                                    current,
                                                )

                                # Set the acquisition state item
                                if data["status"]["state"] == "idle":
                                    self._params.set(
                                        "status/acquisition_complete", True
                                    )
                        else:
                            self._params.set("status/connected", False)
                            self._params.set("status/detector/version_check", False)
                        logger.debug("self._params: %s", self._params)

                        config_dict = self.create_config_request(self._params)
                        reply = self._send("get", "config", config_dict)

                        if reply is not None:
                            logger.debug("Raw reply: %s", reply)
                            if LATRDMessage.MSG_TYPE_RESPONSE in reply.msg_type:
                                data = reply["data"]["config"]
                                logger.debug("Reply data: %s", data)
                                self.update_config(self._params, data)

                        logger.debug("Status items: %s", self._params)
                        logger.debug("Config parameters: %s", self._params)

                except Exception as ex:
                    logger.error("Exception: %s", ex)

    def create_config_request(self, config):
        config_dict = {}
        for item in config:
            if isinstance(config[item], dict):
                config_dict[item] = self.create_config_request(config[item])
            else:
                config_dict[item] = None
        return config_dict

    def update_config(self, params, data):
        for item in data:
            logger.debug("Setting parameter for data item: %s", item)
            if isinstance(data[item], dict):
                if item in params:
                    self.update_config(params[item], data[item])
            else:
                try:
                    if item in params:
                        logger.debug("Setting value to: %s", str(data[item]))
                        params[item].set_value(data[item])
                except Exception as ex:
                    logger.error(f"Couldn't set param {item} to {data[item]}")
                    logger.error("Exception thrown: %s", ex)
