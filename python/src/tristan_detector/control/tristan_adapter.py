import asyncio
import logging

from odin.adapters.adapter import (
    ApiAdapterResponse,
    request_types,
    response_types,
    wants_metadata,
)
from odin.adapters.async_adapter import AsyncApiAdapter
from odin.adapters.parameter_tree import ParameterTreeError
from tornado.escape import json_decode

from .tristan_detector import DetectorTimeoutError, TristanDetector

logger = logging.getLogger(__name__)


class TristanAdapter(AsyncApiAdapter):
    """An odin-control adapter for a Tristan detector

    This class provides the adapter interface between the ODIN server and the Tristan
    detector system. It is a thin layer that translates HTTP verbs into calls on a
    TristanDetector controller, which owns all communication with the hardware.

    It is an async adapter so that requests which wait on the detector (PUTs, which
    can take up to ~20 s for start_acquisition) run in a worker thread instead of
    blocking the odin server's event loop. GETs only read locally stored state, so
    they are answered directly.

    Configuration options:
        endpoint: ZeroMQ endpoint of the detector control interface (required)
        firmware: expected detector software version, used for status/version_check
        udp_file: path of the UDP configuration JSON sent to the detector on connect
        update_interval: seconds between status/config polls of the detector
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        endpoint = self.options.get("endpoint")
        if not endpoint:
            raise RuntimeError("No endpoint specified for the Tristan detector")

        self._controller = TristanDetector(
            endpoint,
            self.options.get("firmware", ""),
            self.options.get("udp_file", "./udp_tristan.json"),
            float(self.options.get("update_interval", 0.5)),
            module=self.name,
        )

    @request_types("application/json", "application/vnd.odin-native")
    @response_types("application/json", default="application/json")
    async def get(self, path, request):
        """Handle an HTTP GET request by reading from the controller

        :param path: URI path of the GET request
        :param request: Tornado HTTP request object
        :return: ApiAdapterResponse object to be returned to the client
        """
        try:
            response = self._controller.get(path.strip("/"), wants_metadata(request))
            status_code = 200
        except ParameterTreeError as error:
            response = {"error": f"{self.name} GET error: {error}"}
            status_code = 400

        return ApiAdapterResponse(response, status_code=status_code)

    @request_types("application/json", "application/vnd.odin-native")
    @response_types("application/json", default="application/json")
    async def put(self, path, request):
        """Handle an HTTP PUT request by passing the decoded body to the controller

        The body may be empty (e.g. for commands), a JSON document or a plain string.
        The controller's result (the detector's reply) is returned as the body. The
        controller call waits on the detector, so it runs in a worker thread.

        :param path: URI path of the PUT request
        :param request: Tornado HTTP request object
        :return: ApiAdapterResponse object to be returned to the client
        """
        try:
            response = await asyncio.to_thread(
                self._controller.put, path.strip("/"), self._decode_body(request.body)
            )
            status_code = 200
        except (ParameterTreeError, ValueError) as error:
            response = {"error": f"{self.name} PUT error: {error}"}
            status_code = 400
        except DetectorTimeoutError as error:
            response = {"error": f"{self.name} PUT error: {error}"}
            status_code = 408

        return ApiAdapterResponse(response, status_code=status_code)

    @request_types("application/json", "application/vnd.odin-native")
    @response_types("application/json", default="application/json")
    async def delete(self, path, request):
        """Handle an HTTP DELETE request by passing it to the controller

        :param path: URI path of the DELETE request
        :param request: Tornado HTTP request object
        :return: ApiAdapterResponse object to be returned to the client
        """
        try:
            self._controller.delete(path.strip("/"))
            response, status_code = {}, 200
        except NotImplementedError as error:
            response = {"error": f"{self.name} DELETE error: {error}"}
            status_code = 501

        return ApiAdapterResponse(response, status_code=status_code)

    async def cleanup(self):
        """Stop the controller's background thread and close the detector channel

        This can wait for an in-progress poll to finish, so it runs in a worker thread.
        """
        await asyncio.to_thread(self._controller.shutdown)

    @staticmethod
    def _decode_body(body):
        """Decode a request body into a Python value

        Native (inter-adapter) requests already carry a Python object. Otherwise an
        empty body decodes to None, valid JSON to its value and anything else is
        treated as a plain string.
        """
        if not isinstance(body, str | bytes):
            return body
        if isinstance(body, bytes):
            body = body.decode()
        if not body.strip():
            return None
        try:
            return json_decode(body)
        except ValueError:
            return body
