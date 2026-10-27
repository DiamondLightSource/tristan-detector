import logging

from odin_data.control.odin_data_adapter import OdinDataAdapter

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

        # Read configuration from self.options
        self._endpoint = self.options.get("endpoint", "")
        self._api = self.options.get("api", "")
        self._firmware = self.options.get("firmware", "")
        self._udp_file = self.options.get("udp_file", "./udp_tristan.json")
        self._update_interval = float(self.options.get("update_interval", 0.5))

        if not self._endpoint or not self._api:
            raise RuntimeError("No endpoint and/or api option specified")

        # Create the detector (controller)
        self._controller = TristanDetector(
            self._endpoint, self._api,
            self._firmware, self._udp_file, self._update_interval
        )
