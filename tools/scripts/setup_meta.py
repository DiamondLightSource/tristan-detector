import argparse

from odin_data.control.ipc_client import IpcClient
from odin_data.control.ipc_message import IpcMessage


def send_configuration(self, config, target):
    _success, _reply = self._client.send_configuration(config, target)


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--port", default=5659, help="Control port of Meta Listener"
    )
    args = parser.parse_args()
    return args


def main():
    args = options()

    client = IpcClient("127.0.0.1", args.port)

    msg = IpcMessage("cmd", "configure")
    msg.set_param("acquisition_id", "test")
    _success, reply = client._send_message(msg, 1.0)
    print(reply)
    # if reply is not None:
    #    empty = reply['params']['buffers']['empty']
    #    mapped = reply['params']['buffers']['mapped']
    #    total = empty + mapped
    #    print("Buffers Free {} out of a total {}".format(empty, total))
    # time.sleep(1.0)


if __name__ == "__main__":
    main()
