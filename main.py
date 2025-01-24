import json
import logging
import signal
import sys

from pyhap.accessory_driver import AccessoryDriver

from accessory import Lock
from repository import Repository
from service import Service
from util.bfclf import BroadcastFrameContactlessFrontend

# By default, this file is located in the same folder as the project
CONFIGURATION_FILE_PATH = "configuration.json"


def load_configuration(path=CONFIGURATION_FILE_PATH) -> dict:
    return json.load(open(path, "r+"))


def configure_logging(config: dict):
    log = logging.getLogger()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)8s] %(module)-18s:%(lineno)-4d %(message)s"
    )
    hdlr = logging.StreamHandler(sys.stdout)
    log.setLevel(config.get("level", logging.INFO))
    hdlr.setFormatter(formatter)
    log.addHandler(hdlr)
    return log


def configure_hap_accessory(hap_config: dict, homekey_config: dict, homekey_service=None):
    driver = AccessoryDriver(port=hap_config["port"], persist_file=hap_config["persist"])
    accessory = Lock(
        driver,
        homekey_config["name"],
        manufacturer=homekey_config["manufacturer"],
        serialNumber=homekey_config["serialNumber"],
        model=homekey_config["model"],
        firmware=homekey_config["firmware"],
        service=homekey_service,
        lock_state_at_startup=int(hap_config.get("default") != "unlocked")
    )
    driver.add_accessory(accessory=accessory)
    return driver, accessory


def configure_nfc_device(config: dict):
    clf = BroadcastFrameContactlessFrontend(
        path=config.get("path", None) or f"tty:{config.get('port')}:{config.get('driver')}",
        broadcast_enabled=config.get("broadcast", True),
    )
    return clf


def configure_homekey_service(config: dict, nfc_device, repository=None):
    service = Service(
        nfc_device,
        repository=repository or Repository(config["persist"]),
        express=config.get("express", True),
        finish=config.get("finish"),
        flow=config.get("flow"),
        # Poll no more than ~6 times a second by default
        throttle_polling=float(config.get("throttle_polling") or 0.15),
    )
    return service


def main():
    config = load_configuration()
    log = configure_logging(config["logging"])

    nfc_config = config["nfc"]
    hap_config = config["hap"]
    homekey_config = config["homekey"]
    nfc_device = configure_nfc_device(nfc_config)
    homekey_service = configure_homekey_service(homekey_config, nfc_device)
    hap_driver, _ = configure_hap_accessory(hap_config, homekey_config, homekey_service)

    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(
            s,
            lambda *_: (
                log.info(f"SIGNAL {s}"),
                homekey_service.stop(),
                hap_driver.stop(),
            ),
        )

    homekey_service.start()
    hap_driver.start()


if __name__ == "__main__":
    main()
