import argparse
import time

from odin_data.control.ipc_client import IpcClient
from odin_data.control.ipc_message import IpcMessage


def send_configuration(self, config, target):
    _success, _reply = self._client.send_configuration(config, target)


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=5000, help="Control port of FR")
    args = parser.parse_args()
    return args


def main():
    args = options()

    client = IpcClient("127.0.0.1", args.port)

    while True:
        msg = IpcMessage("cmd", "status")
        _success, reply = client._send_message(msg, 1.0)
        # print(reply)
        if reply is not None:
            empty = reply["params"]["buffers"]["empty"]
            mapped = reply["params"]["buffers"]["mapped"]
            total = empty + mapped
            print(f"Buffers Free {empty} out of a total {total}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
