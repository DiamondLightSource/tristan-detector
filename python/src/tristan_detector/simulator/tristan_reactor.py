import logging

import zmq


class TristanReactor:
    """Poll registered channels and call each one's callback when it has a message"""

    # Longest time a poll blocks, so that stop() takes effect promptly
    MAX_POLL_TIMEOUT_MS = 100

    def __init__(self):
        logging.basicConfig(format="%(asctime)-15s %(message)s")
        self._log = logging.getLogger(".".join([__name__, self.__class__.__name__]))
        self._log.setLevel(logging.DEBUG)
        self._terminate_reactor = False
        self._callbacks = {}
        self._pollsize = 0
        self._needs_rebuild = True
        self._channels = {}

    def register_channel(self, channel, callback):
        # Add channel to channel map
        self._channels[channel.socket] = channel
        self._callbacks[channel.socket] = callback
        # Signal a rebuild is required
        self._needs_rebuild = True

    def stop(self):
        """Ask the reactor loop to exit; safe to call from another thread"""
        self._terminate_reactor = True

    def run(self):
        # Loop until the terminate flag is set
        while not self._terminate_reactor:
            # If the poll items list needs rebuilding, do it now
            if self._needs_rebuild:
                self.rebuild_pollitems()

            # If there are no channels to poll, break out of the loop cleanly
            if self._pollsize == 0:
                break

            try:
                pollrc = dict(self._poller.poll(self.MAX_POLL_TIMEOUT_MS))

                for sock in pollrc:
                    if pollrc[sock] == zmq.POLLIN:
                        try:
                            self._callbacks[sock]()
                        except Exception as e:
                            self._log.debug(
                                "Caught exception in reactor-callback function"
                            )
                            self._log.exception(e)

            except Exception as e:
                self._log.exception(e)
                break

        return 0

    def rebuild_pollitems(self):
        self._poller = zmq.Poller()

        self._pollsize = len(self._channels)

        if self._pollsize > 0:
            for channel in self._channels:
                self._log.debug("Registering %s for polling", channel)
                self._poller.register(channel, zmq.POLLIN)

        self._needs_rebuild = False
