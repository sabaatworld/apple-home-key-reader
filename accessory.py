import functools
import json
import logging
import requests

from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_DOOR_LOCK

from service import Service

log = logging.getLogger()


# Lock class performs no logic, forwarding requests to Service class
class Lock(Accessory):
    category = CATEGORY_DOOR_LOCK

    def __init__(self, *args, manufacturer: str, serialNumber: str, model: str, firmware: str, ha_config: dict, service: Service, lock_state_at_startup=1, **kwargs):
        self.manufacturer = manufacturer
        self.serialNumber = serialNumber
        self.model = model
        self.firmware = firmware
        self.ha_config = ha_config
        if self.ha_config:
            self.ha_server_address = self.get_ha_server_address()
            self.ha_api_token = ha_config.get("apiToken")
            self.ha_entity_id = ha_config.get("entityId")

        super().__init__(*args, **kwargs)
        self._last_client_public_keys = None

        if self.ha_config:
            lock_state_at_startup = self.get_lock_state_from_ha()
        self._lock_target_state = lock_state_at_startup
        self._lock_current_state = lock_state_at_startup

        self.service = service
        self.service.on_endpoint_authenticated = self.on_endpoint_authenticated
        self.add_lock_service()
        self.add_nfc_access_service()
        self.add_unpair_hook()


    def on_endpoint_authenticated(self, endpoint):
        self._lock_target_state = 0 if self._lock_current_state else 1
        log.info(
            f"Toggling lock state due to endpoint authentication event {self._lock_target_state} -> {self._lock_current_state} {endpoint}"
        )
        self.lock_target_state.set_value(self._lock_target_state, should_notify=True)
        self._lock_current_state = self._lock_target_state
        self.lock_current_state.set_value(self._lock_current_state, should_notify=True)

        if self.ha_config:
            self.set_lock_state_in_ha(self._lock_target_state)

    def add_unpair_hook(self):
        unpair = self.driver.unpair

        @functools.wraps(unpair)
        def patched_unpair(client_uuid):
            unpair(client_uuid)
            self.on_unpair(client_uuid)

        self.driver.unpair = patched_unpair

    def add_preload_service(self, service, chars=None, unique_id=None):
        """Create a service with the given name and add it to this acc."""
        if isinstance(service, str):
            service = self.driver.loader.get_service(service)
        if unique_id is not None:
            service.unique_id = unique_id
        if chars:
            chars = chars if isinstance(chars, list) else [chars]
            for char_name in chars:
                if isinstance(char_name, str):
                    char = self.driver.loader.get_char(char_name)
                    service.add_characteristic(char)
                else:
                    service.add_characteristic(char_name)
        self.add_service(service)
        return service

    def add_info_service(self):
        serv_info = self.driver.loader.get_service("AccessoryInformation")
        serv_info.configure_char("Name", value=self.display_name)
        serv_info.configure_char("Manufacturer", value=self.manufacturer)
        serv_info.configure_char("SerialNumber", value=self.serialNumber)
        serv_info.configure_char("Model", value=self.model)
        serv_info.add_characteristic(self.driver.loader.get_char("FirmwareRevision"))
        serv_info.configure_char("FirmwareRevision", value=self.firmware)
        serv_info.add_characteristic(self.driver.loader.get_char("HardwareFinish"))
        serv_info.configure_char(
            "HardwareFinish", getter_callback=self.get_hardware_finish
        )
        self.add_service(serv_info)

    def add_lock_service(self):
        self.service_lock_mechanism = self.add_preload_service("LockMechanism")

        self.lock_current_state = self.service_lock_mechanism.configure_char(
            "LockCurrentState", getter_callback=self.get_lock_current_state, value=0
        )

        self.lock_target_state = self.service_lock_mechanism.configure_char(
            "LockTargetState",
            getter_callback=self.get_lock_target_state,
            setter_callback=self.set_lock_target_state,
            value=0,
        )

        self.service_lock_management = self.add_preload_service("LockManagement")

        self.lock_control_point = self.service_lock_management.configure_char(
            "LockControlPoint",
            setter_callback=self.set_lock_control_point,
        )

        self.lock_version = self.service_lock_management.configure_char(
            "Version",
            getter_callback=self.get_lock_version,
        )

    def add_nfc_access_service(self):
        self.service_nfc = self.add_preload_service("NFCAccess")

        self.char_nfc_access_supported_configuration = self.service_nfc.configure_char(
            "NFCAccessSupportedConfiguration",
            getter_callback=self.get_nfc_access_supported_configuration,
        )

        self.char_nfc_access_control_point = self.service_nfc.configure_char(
            "NFCAccessControlPoint",
            getter_callback=self.get_nfc_access_control_point,
            setter_callback=self.set_nfc_access_control_point,
        )

        self.configuration_state = self.service_nfc.configure_char(
            "ConfigurationState", getter_callback=self.get_configuration_state
        )

    def _update_hap_pairings(self):
        client_public_keys = set(self.clients.values())
        if self._last_client_public_keys == client_public_keys:
            return
        self._last_client_public_keys = client_public_keys
        self.service.update_hap_pairings(client_public_keys)

    def get_lock_current_state(self):
        log.info("get_lock_current_state")
        if self.ha_config:
            self._lock_target_state = self._lock_current_state = self.get_lock_state_from_ha()
            self.lock_current_state.set_value(self._lock_current_state, should_notify=True)
        return self._lock_current_state

    def get_lock_target_state(self):
        log.info("get_lock_target_state")
        return self._lock_target_state

    def set_lock_target_state(self, value):
        log.info(f"set_lock_target_state {value}")
        self._lock_target_state = self._lock_current_state = value
        self.lock_current_state.set_value(self._lock_current_state, should_notify=True)

        if self.ha_config:
            self.set_lock_state_in_ha(value)

        return self._lock_target_state

    def get_lock_version(self):
        log.info("get_lock_version")
        return ""

    def set_lock_control_point(self, value):
        log.info(f"set_lock_control_point: {value}")

    # All methods down here are forwarded to Service
    def get_hardware_finish(self):
        self._update_hap_pairings()
        log.info("get_hardware_finish")
        return self.service.get_hardware_finish()

    def get_nfc_access_supported_configuration(self):
        self._update_hap_pairings()
        log.info("get_nfc_access_supported_configuration")
        return self.service.get_nfc_access_supported_configuration()

    def get_nfc_access_control_point(self):
        self._update_hap_pairings()
        log.info("get_nfc_access_control_point")
        return self.service.get_nfc_access_control_point()

    def set_nfc_access_control_point(self, value):
        self._update_hap_pairings()
        log.info(f"set_nfc_access_control_point {value}")
        return self.service.set_nfc_access_control_point(value)

    def get_configuration_state(self):
        self._update_hap_pairings()
        log.info("get_configuration_state")
        return self.service.get_configuration_state()

    @property
    def clients(self):
        return self.driver.state.paired_clients

    def on_unpair(self, client_id):
        log.info(f"on_unpair {client_id}")
        self._update_hap_pairings()

    def get_lock_state_from_ha(self):
        try:
            # Fetch the current cover state from Home Assistant
            url = f"{self.ha_server_address}/api/states/{self.ha_entity_id}"
            headers = {
                "Authorization": f"Bearer {self.ha_api_token}",
                "Content-Type": "application/json",
            }
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                state = response.json()
                # Set lock state based on cover state
                return 1 if state.get("state") == "closed" else 0
        except Exception as e:
            log.error(f"Error fetching cover state from Home Assistant: {e}")
        return 0

    # Method to set the cover state in Home Assistant (locked = closed, unlocked = open)
    def set_lock_state_in_ha(self, lock_target_state):
        cover_target_state = "closed" if lock_target_state == 1 else "open"
        service = "close_cover" if cover_target_state == 'closed' else "open_cover"

        try:
            url = f"{self.ha_server_address}/api/services/cover/{service}"
            headers = {
                "Authorization": f"Bearer {self.ha_api_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "entity_id": self.ha_entity_id
            }
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                log.info(f"Successfully set cover state to {cover_target_state}")
            else:
                log.error(f"Failed to set cover state to {cover_target_state}: {response.text}")
        except Exception as e:
            log.error(f"Error setting cover state in Home Assistant: {e}")

    def get_ha_server_address(self):
        scheme = "https" if self.ha_config.get("useSSL") else "http"
        return f"{scheme}://{self.ha_config.get('serverAddress')}"
