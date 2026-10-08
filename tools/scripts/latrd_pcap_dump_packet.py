"""
LATRDProducer - load LATRD packets from packet capture file and send via UDP.

Tim Nicholls, STFC Application Engineering Group.
"""

import argparse
import logging
import os
import socket
import struct
import threading
import time

import dpkt

logger = logging.getLogger(__name__)


class LATRDPacket:
    IDLE_PACKET_MASK = 0x000000000003F800
    PRODUCER_ID_MASK = 0x03FC000000000000
    TIME_SLICE_WRAP_MASK = 0x0003FFFFFFFC0000
    TIME_SLICE_BUFFER_MASK = 0x000000FF00000000
    WORD_COUNT_MASK = 0x00000000000007FF
    NO_OF_BUFFERS = 4


class LATRDProducerDefaults:
    """
    Holds default values for frame producer parameters.
    """

    def __init__(self):

        self.ip_addr = "localhost"
        self.port_list = "61649"
        self.num_frames = 0
        self.num_idle = 5
        self.duration = 6.0
        self.drop_frac = 0
        self.drop_list = None

        self.log_level = "info"
        self.log_levels = {
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG,
        }

        self.pcap_file = "latrd.pcap"


class Range(argparse.Action):
    """
    Range validating action for argument parser.
    """

    def __init__(self, min=None, max=None, *args, **kwargs):
        self.min = min
        self.max = max
        kwargs["metavar"] = f"[{self.min}-{self.max}]"
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        if not self.min <= value <= self.max:
            msg = f"invalid choice: {value!r} (choose from [{self.min}-{self.max}])"
            raise argparse.ArgumentError(self, msg)
        setattr(namespace, self.dest, value)


class CsvAction(argparse.Action):
    """
    Comma separated list of values action for argument parser.
    """

    def __init__(self, val_type=None, *args, **kwargs):
        self.val_type = val_type
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        item_list = []
        try:
            for item_str in value.split(","):
                item_list.append(self.val_type(item_str))
        except ValueError as e:
            raise argparse.ArgumentError(self, e)
        setattr(namespace, self.dest, item_list)


class LATRDFrameProducer:
    """
    LATRD frame procducer - loads frame packets data from capture file and replays it to
    a receiver via a UDP socket.
    """

    def __init__(self):
        """
        Initialise the packet producer object, setting defaults and parsing command-line options.
        """
        # IDLE packet record
        self._idle_packet = None
        self._data_packet = None

        # Create an empty list for packet storage
        self._packets = []

        # Create an empty list for timeslice information
        self._ts = []

        # Load default parameters
        self.defaults = LATRDProducerDefaults()

        self._no_of_ports = 1

        # Set the terminal width for argument help formatting
        try:
            term_columns = int(os.environ["COLUMNS"]) - 2
        except (KeyError, ValueError):
            term_columns = 100

        # Build options for the argument parser
        parser = argparse.ArgumentParser(
            prog="latrd_pcap_replay.py",
            description="LATRD frame producer",
            formatter_class=lambda prog: argparse.ArgumentDefaultsHelpFormatter(
                prog, max_help_position=40, width=term_columns
            ),
        )

        parser.add_argument(
            "pcap_file",
            type=argparse.FileType("rb"),
            default=self.defaults.pcap_file,
            help="Packet capture file to load",
        )

        parser.add_argument(
            "--address",
            "-a",
            type=str,
            dest="ip_addr",
            default=self.defaults.ip_addr,
            metavar="ADDR",
            help="Hostname or IP address to transmit UDP frame data to",
        )
        parser.add_argument(
            "--port",
            "-p",
            type=str,
            val_type=int,
            dest="ports",
            action=CsvAction,
            default=self.defaults.port_list,
            metavar="PORT[,PORT,...]",
            help="Comma separatied list of port numbers to transmit UDP frame data to",
        )
        parser.add_argument(
            "--frames",
            "-n",
            type=int,
            dest="num_frames",
            default=self.defaults.num_frames,
            metavar="FRAMES",
            help="Number of frames to transmit (0 = send all frames found in packet capture file",
        )
        parser.add_argument(
            "--duration",
            "-d",
            type=float,
            dest="duration",
            default=self.defaults.duration,
            metavar="INTERVAL",
            help="Duration in seconds for sending data packets",
        )
        parser.add_argument(
            "--idle",
            "-i",
            type=float,
            dest="num_idle",
            default=self.defaults.num_idle,
            metavar="IDLE",
            help="Number of idle packets to send before and after",
        )
        parser.add_argument(
            "--pkt_gap",
            type=int,
            dest="pkt_gap",
            metavar="PACKETS",
            help="Insert brief pause between every N packets",
        )
        parser.add_argument(
            "--drop_frac",
            type=float,
            dest="drop_frac",
            min=0.0,
            max=1.0,
            action=Range,
            default=self.defaults.drop_frac,
            metavar="FRACTION",
            help="Fraction of packets to drop",
        )
        parser.add_argument(
            "--drop_list",
            type=int,
            nargs="+",
            dest="drop_list",
            default=self.defaults.drop_list,
            help="Packet number(s) to drop from each frame",
        )
        parser.add_argument(
            "--logging",
            type=str,
            dest="log_level",
            default=self.defaults.log_level,
            choices=self.defaults.log_levels.keys(),
            help="Set logging output level",
        )

        # Parse arguments
        self.args = parser.parse_args()

        # Map logging level option onto real level
        if self.args.log_level in self.defaults.log_levels:
            log_level = self.defaults.log_levels[self.args.log_level]
        else:
            log_level = self.defaults.log_levels[self.defaults.log_level]

        # Set up logging
        logging.basicConfig(
            level=log_level,
            format="%(levelname)1.1s %(message)s",
            datefmt="%y%m%d %H:%M:%S",
        )

        # Initialise the packet capture file reader
        self.pcap = dpkt.pcap.Reader(self.args.pcap_file)

    def run(self):
        """
        Run the frame producer.
        """
        self.load_pcap()

    #        self.send_packets()

    def load_pcap(self):
        """
        Load frame packets from a packet capture file.
        """

        # Set up packet capture counters

        # Initialise current frame

        logger.info(
            "Extracting LATRD packets from PCAP file %s", self.args.pcap_file.name
        )

        # Loop over packets in capture
        for _, buf in self.pcap:
            # Extract Ethernet, IP and UDP layers from packet buffer
            eth_layer = dpkt.ethernet.Ethernet(buf)
            ip_layer = eth_layer.data
            udp_layer = ip_layer.data

            # Unpack the packet header
            if len(udp_layer.data) >= 24:
                (zero_pkt, hdr_pkt_1, hdr_pkt_2) = struct.unpack(
                    "<QQQ", udp_layer.data[:24]
                )

                # Check for an idle packet
                if (
                    hdr_pkt_1 & LATRDPacket.IDLE_PACKET_MASK
                ) == LATRDPacket.IDLE_PACKET_MASK:
                    if self._idle_packet is None:
                        logger.debug("IDLE Packet processed...")
                        pkt_length = len(udp_layer.data[24:])
                        logger.debug(f"Length of packet: {pkt_length}")
                        words = struct.unpack(
                            f"<{pkt_length / 8}Q", udp_layer.data[24:]
                        )
                        logger.debug(f"0x{zero_pkt:016X}")
                        logger.debug(f"0x{hdr_pkt_1:016X}")
                        logger.debug(f"0x{hdr_pkt_2:016X}")
                        for word in words:
                            logger.debug(f"0x{word:016X}")
                        self._idle_packet = udp_layer.data
                else:
                    # Store the packets exactly as recorded
                    self._packets.append(udp_layer.data)
                    # Store the source timeslice so that we can use it for round robin
                    ts_wrap = (hdr_pkt_1 & LATRDPacket.TIME_SLICE_WRAP_MASK) >> 18
                    ts_buff = (hdr_pkt_2 & LATRDPacket.TIME_SLICE_BUFFER_MASK) >> 32
                    self._ts.append((ts_wrap * LATRDPacket.NO_OF_BUFFERS) + ts_buff)
                    # logger.debug("Ts ID: %d", (ts_wrap * LATRDPacket.NO_OF_BUFFERS) + ts_buff)
                    if self._data_packet is None:
                        logger.debug("Data Packet processed...")
                        pkt_length = len(udp_layer.data[24:])
                        logger.debug(f"Length of packet: {pkt_length}")
                        words = struct.unpack(
                            f"<{pkt_length / 8}Q", udp_layer.data[24:]
                        )
                        logger.debug(f"0x{zero_pkt:016X}")
                        logger.debug(f"0x{hdr_pkt_1:016X}")
                        logger.debug(f"0x{hdr_pkt_2:016X}")
                        for word in words:
                            logger.debug(f"0x{word:016X}")
                        self._data_packet = udp_layer.data

            else:
                logger.debug(
                    "Ignoring data packet with length [%s]...", len(udp_layer.data)
                )

        logger.debug("Number of data packets processed: %d", len(self._packets))

    def send_packets(self):

        send_threads = []
        if isinstance(self.args.ports, str):
            self.args.ports = [self.args.ports]

        self._no_of_ports = len(self.args.ports)
        logger.info(
            f"Launching threads to send packets to {len(self.args.ports)} destination ports"
        )

        for index, port in enumerate(self.args.ports):
            send_thread = threading.Thread(
                target=self._send_packets, args=(int(port), int(index))
            )
            send_threads.append(send_thread)
            send_thread.start()

    def _send_packets(self, port, index):
        """
        Send loaded packets over UDP socket.
        """

        # Create the UDP socket
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        if udp_socket is None:
            logger.error("Failed to open UDP socket")
            return

        idle_bytes_sent = 0
        idle_packets_sent = 0
        logger.info("Sending %d idle packets at 1 Hz", self.args.num_idle)
        # Start by sending Idle packets at a rate of 1Hz
        for packets in range(int(self.args.num_idle)):
            # Send the packet over the UDP socket
            try:
                idle_bytes_sent += udp_socket.sendto(
                    self._idle_packet, (self.args.ip_addr, port)
                )
                idle_packets_sent += 1
                # Add 1 second delay
                time.sleep(1.0)
            except OSError as exc:
                logger.error("Got error sending frame packet: %s", exc)
                break

        # Packet delay is total duration / number of packets
        logger.info(
            "Sending %d data packets in %f seconds",
            len(self._packets) / self._no_of_ports,
            self.args.duration,
        )
        data_bytes_sent = 0
        data_packets_sent = 0
        delay = float(self.args.duration) / float(
            len(self._packets) / self._no_of_ports
        )
        for packet, ts_id in zip(self._packets, self._ts):
            # Send the packet over the UDP socket
            try:
                if ts_id % self._no_of_ports == index:
                    data_bytes_sent += udp_socket.sendto(
                        packet, (self.args.ip_addr, port)
                    )
                    data_packets_sent += 1
                    # Add 1 second delay
                    if delay > 0.001:
                        time.sleep(delay)
            except OSError as exc:
                logger.error("Got error sending frame packet: %s", exc)
                break

        time.sleep(1.0)
        idle_bytes_sent = 0
        idle_packets_sent = 0
        logger.info("Sending %d idle packets at 1 Hz", self.args.num_idle)
        # Start by sending Idle packets at a rate of 1Hz
        for packets in range(int(self.args.num_idle)):
            # Send the packet over the UDP socket
            try:
                idle_bytes_sent += udp_socket.sendto(
                    self._idle_packet, (self.args.ip_addr, port)
                )
                idle_packets_sent += 1
                # Add 1 second delay
                time.sleep(1.0)
            except OSError as exc:
                logger.error("Got error sending frame packet: %s", exc)
                break

        udp_socket.close()


if __name__ == "__main__":
    LATRDFrameProducer().run()
