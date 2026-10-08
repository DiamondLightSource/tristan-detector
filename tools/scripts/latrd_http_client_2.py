import argparse
import getpass
import json
import logging

import requests

logger = logging.getLogger(__name__)


class LATRDClient:
    def __init__(self, address="127.0.0.1:8888", api=0.1):
        self._address = address
        self._api = api
        self._url = "http://" + str(self._address) + "/api/" + str(self._api)
        self._user = getpass.getuser()

    def command(self, adapter, command):
        try:
            url = self._url + "/" + adapter + "/command/" + command
            logger.error("Sending msg to: %s", url)
            result = requests.put(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ).json()
        except requests.exceptions.RequestException:
            result = {
                "error": "Exception during HTTP request, check address and Odin server instance"
            }
            logger.exception(result["error"])
        return result

    def set(self, adapter, parameter, value):
        try:
            url = self._url + "/" + adapter + "/config/" + parameter
            logger.error("Sending msg to: %s", url)
            result = requests.put(
                url,
                data=json.dumps(value),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ).json()
        except requests.exceptions.RequestException:
            result = {
                "error": "Exception during HTTP request, check address and Odin server instance"
            }
            logger.exception(result["error"])
        return result

    def get(self, adapter, parameter):
        try:
            url = self._url + "/" + adapter + "/version/" + parameter
            logger.error("Sending msg to: %s", url)
            result = requests.get(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ).json()
        except requests.exceptions.RequestException:
            result = {
                "error": "Exception during HTTP request, check address and Odin server instance"
            }
            logger.exception(result["error"])
        return result

    def engineering_put(self, adapter, value):
        try:
            url = self._url + "/" + adapter + "/engineering_put"
            logger.error("Sensing msg to: %s", url)
            result = requests.put(
                url,
                data=json.dumps(value),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ).json()
        except requests.exceptions.RequestException:
            result = {
                "error": "Exception during HTTP request, check address and Odin server instance"
            }
            logger.exception(result["error"])
        return result

    def engineering_get(self, adapter, value):
        try:
            url = self._url + "/" + adapter + "/engineering_get"
            logger.error("Sensing msg to: %s", url)
            result = requests.put(
                url,
                data=json.dumps(value),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ).json()
        except requests.exceptions.RequestException:
            result = {
                "error": "Exception during HTTP request, check address and Odin server instance"
            }
            logger.exception(result["error"])
        return result

    def set_fp(self, parameter, value):
        self.set("fp", parameter, value)

    def get_fr_status(self):
        return self.get("fr", "")

    def get_fp_status(self):
        return self.get("fp", "")

    def get_ctrl_status(self):
        return self.get("ctrl", "")

    def set_ctrl_Exposure(self, value):
        return self.set("ctrl", "Exposure/" + str(value), None)


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a", "--address", default="127.0.0.1:8888", help="Odin control server endpoint"
    )
    parser.add_argument(
        "-i",
        "--init",
        action="store_true",
        help="Initialise the FrameProcessor application",
    )
    args = parser.parse_args()
    return args


def main():
    args = options()

    client = LATRDClient(args.address)

    #    print("Reset statistics: {}".format(client.command('fp', 'reset_statistics')))
    print(f"FP Version: {client.get_fp_status()}")
    print(f"FR Version: {client.get_fr_status()}")


#    print("Set Exposure : {}".format(client.set_ctrl_Exposure(1)))
#    print("Get Exposure : {}".format(client.engineering_get('ctrl', {"Exposure":None})))


if __name__ == "__main__":
    main()
