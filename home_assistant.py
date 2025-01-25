import json
import logging
import requests
import threading
import time
import websockets.sync.client as ws_client

log = logging.getLogger()


class HomeAssistant:
    websocket_reconnect_interval = 5
    ha_entity_state_subscription_id = 21

    def __init__(self, ha_config: dict, apply_lock_state: callable):
        self.ha_config = ha_config
        self.ha_server_address = self.get_ha_server_address()
        self.ha_ws_address = self.get_ha_ws_address()
        self.ha_api_token = ha_config.get("apiToken")
        self.ha_entity_id = ha_config.get("entityId")
        self.apply_lock_state = apply_lock_state

        self.start_websocket_listener_thread()

    def get_ha_server_address(self):
        scheme = "https" if self.ha_config.get("useSSL") else "http"
        return f"{scheme}://{self.ha_config.get('serverAddress')}"
    
    def get_ha_ws_address(self):
        scheme = "wss" if self.ha_config.get("useSSL") else "ws"
        return f"{scheme}://{self.ha_config.get('serverAddress')}"

    def get_cover_state_from_ha(self):
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
                return state.get("state")
            else:
                log.error(f"Non 200 response when getting cover state from HA: {response.text}")
                raise ConnectionError(f"Non 200 response when getting cover state from HA: {response.text}")
        except Exception as e:
            log.error(f"Error fetching cover state from HA: {e}")
            raise ConnectionError(f"Error fetching cover state from HA: {e}")

    # Method to set the cover state in Home Assistant (locked = closed, unlocked = open)
    def set_lock_state_in_ha(self, lock_target_state):
        cover_target_state = "closed" if lock_target_state == 1 else "open"
        log.info(f"Setting cover state to {cover_target_state} in HA")
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
                raise ConnectionError(f"Failed to set cover state to {cover_target_state}: {response.text}")
        except Exception as e:
            log.error(f"Error setting cover state in Home Assistant: {e}")
    
    def start_websocket_listener_thread(self):
        # Start the websocket listener in a separate thread
        thread = threading.Thread(
            target=self.websocket_listener_with_reconnect,
            daemon=True
        )
        thread.start()

    def websocket_listener_with_reconnect(self):
        while True:
            try:
                self.websocket_listener()
            except Exception as e:
                log.error(f"WebSocket listener encountered an error: {e}. Reconnecting in {HomeAssistant.websocket_reconnect_interval} seconds...")
                time.sleep(HomeAssistant.websocket_reconnect_interval)  # Wait before reconnecting

    def websocket_listener(self):
        uri = f"{self.ha_ws_address}/api/websocket"
        log.info(f"HA WebSocket URL: {uri}")

        with ws_client.connect(uri) as websocket:
            # Wait for "auth_required" message
            initial_message = websocket.recv()
            initial_data = json.loads(initial_message)
            if initial_data.get("type") == "auth_required":
                log.info("HA Server requires authentication")
                self.websocket_authenticate(websocket)
            else:
                log.error("Unexpected initial message from server")
                raise ConnectionError("Unexpected initial message from server")

            self.subscribe_to_cover_state(websocket)
            self.handle_cover_state(self.get_cover_state_from_ha())

            while True:
                message = websocket.recv()
                message_data = json.loads(message)
                if message_data.get("type") == "event" and message_data.get("id") == HomeAssistant.ha_entity_state_subscription_id:
                    self.process_cover_state_update_message(message_data)

    def websocket_authenticate(self, websocket):
        log.info(f"HA WebSocket Authenticating")
        auth_message = {
            "type": "auth",
            "access_token": self.ha_api_token
        }
        websocket.send(json.dumps(auth_message))
        auth_response = websocket.recv()
        auth_data = json.loads(auth_response)
        if auth_data.get("type") == "auth_ok":
            log.info("WebSocket authentication successful")
        else:
            log.error("WebSocket authentication failed")
            raise ConnectionError("Failed to authenticate with WebSocket")

    def subscribe_to_cover_state(self, websocket):
        subscription_message = {
            "id": HomeAssistant.ha_entity_state_subscription_id,
            "type": "subscribe_trigger",
            "trigger": {
                "platform": "state",
                "entity_id": self.ha_entity_id
            }
        }
        websocket.send(json.dumps(subscription_message))
        log.info(f"Subscribed to state changes for entity: {self.ha_entity_id}")

    def process_cover_state_update_message(self, message_data):
        new_state = message_data["event"]["variables"]["trigger"]["to_state"]["state"]
        self.handle_cover_state(new_state)

    def handle_cover_state(self, cover_state):
        log.info(f"Cover state changed to: {cover_state}")
        if cover_state == "closed":
            new_lock_state = 1
        else:
            new_lock_state = 0
        self.apply_lock_state(new_lock_state)
