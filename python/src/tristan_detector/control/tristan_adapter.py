import logging
import re

from odin.adapters.adapter import (
    ApiAdapterResponse,
    request_types,
    response_types,
)
from odin_data.control.odin_data_adapter import OdinDataAdapter
from tornado.httputil import HTTPServerRequest

from .tristan_detector import TristanDetector

logger = logging.getLogger(__name__)


class TristanAdapter(OdinDataAdapter):
    """An Odin-Data Control adapter for a Tristan detector

    This class provides the adapter interface between the ODIN server and the Tristan
    detector system, transforming the REST-like API HTTP verbs into the appropriate
    Tristan ZeroMQ control messages
    """

    def __init__(self, **kwargs):
        logger.debug("TristanAdapter init called")
        super().__init__(**kwargs)
        # Compile the regex used to resolve paths into actions and resources
        self.path_regexp = re.compile("(.*?)/(.*)")

        # Setup the time between client update requests
        self._update_interval = float(self.options.get("update_interval", 0.5))

        if self._endpoint is None:
            raise RuntimeError(
                "No endpoint specified for the Tristan detector"
            ) from None

        # Read the expected version of the firmware
        try:
            self._firmware = self.options.get("firmware", "")
        except Exception:
            raise RuntimeError(
                "No firmware version specified for the Tristan detector"
            ) from None

        # Read the location of the UDP configuration file
        try:
            self._udp_config_file = self.options.get("udp_file", "./udp_tristan.json")
        except Exception:
            # Use a default if no location if an error occurs
            self._udp_config_file = "./udp_tristan.json"

        if "endpoint" in self.options:
            if "api" in self.options:
                try:
                    self._endpoint = self.options["endpoint"]
                    self._api = self.options["api"]
                    self._detector = TristanDetector(
                        self._endpoint,
                        self._api,
                        self._firmware,
                        self._udp_config_file,
                        self._update_interval,
                    )

                except Exception as e:
                    logger.error(
                        "TristanAdapter failed to create detector object: %s", e
                    )
                    logger.exception(e)
            else:
                logger.warning("No detector api option specified in configuration")
        else:
            logger.warning("No detector endpoint option specified in configuration")

    @request_types("application/json")
    @response_types("application/json", default="application/json")
    def get(self, path: str, request: HTTPServerRequest):
        """
        Implementation of the HTTP GET verb for TristanAdapter

        :param path: URI path of the GET request
        :param request: Tornado HTTP request object
        :return: ApiAdapterResponse object to be returned to the client
        """
        response = {}
        logger.debug("GET path: %s", path)
        logger.debug("GET request: %s", request)

        # Check if the adapter type is being requested
        request_command = path.strip("/")
        if request_command in self.ADODIN_MAPPING:
            request_command = self.ADODIN_MAPPING[request_command]
        if not request_command:
            return ApiAdapterResponse(
                {
                    "status": self._detector.STATUS_PATHS,
                    "config": self._detector.DETECTOR_CONFIG,
                },
                status_code=200,
            )
        if request_command in self._kwargs:
            return ApiAdapterResponse(
                {request_command: self._kwargs[request_command]}, status_code=200
            )

        logger.debug("Full response from FP: %s", response)

        return ApiAdapterResponse(self._detector.get(request_command), status_code=200)

    @request_types("application/json")
    @response_types("application/json", default="application/json")
    def delete(self, path: str, request: HTTPServerRequest):
        """
        Implementation of the HTTP DELETE verb for TristanAdapter

        :param path: URI path of the DELETE request
        :param request: Tornado HTTP request object
        :return: ApiAdapterResponse object to be returned to the client
        """
        response = {"response": f"{self.name}: DELETE on path {path}"}
        status_code = 501

        logger.debug(response)

        return ApiAdapterResponse(response, status_code=status_code)
