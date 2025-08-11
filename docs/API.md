# Apple Home Key Reader – API Documentation

This document describes the public APIs, classes, functions, and components exposed by the project. It’s organized by module with concise descriptions, parameters, return values, and usage examples.

- Project entrypoint: `main.py`
- Core service: `service.py`
- Home Key protocol: `homekey.py`
- Home Assistant bridge: `home_assistant.py`
- HAP bridge accessory: `accessory.py`
- Domain entities and TLV models: `entity.py`
- Repository (state persistence): `repository.py`
- Utilities: `util/*`

---

## main.py

### load_configuration(path: str = CONFIGURATION_FILE_PATH) -> dict
Load `configuration.json`.

Example:
```python
from main import load_configuration
config = load_configuration()
```

### load_ha_configuration(path: str = HA_CONFIGURATION_FILE_PATH) -> dict | None
Load `home-assistant.json` when present.

### configure_logging(config: dict) -> logging.Logger
Initialize console + rotating file logging.

### configure_hap_accessory(hap_config: dict, homekey_config: dict, ha_config: dict | None, homekey_service: Service | None) -> tuple[AccessoryDriver, Lock]
Create and register the HAP `Lock` accessory.

### configure_nfc_device(config: dict) -> BroadcastFrameContactlessFrontend
Create NFC frontend using PN532/USB.

### configure_homekey_service(config: dict, nfc_device, repository: Repository | None) -> Service
Instantiate `Service` with NFC + repository and options.

### main() -> None
Entrypoint: loads config, wires device + service + HAP, starts event loop.

---

## accessory.py

### class Lock(Accessory)
HomeKit Lock accessory that proxies to `Service` and optionally bridges to Home Assistant.

Constructor:
```python
Lock(driver, name,
     manufacturer: str, serialNumber: str, model: str, firmware: str,
     ha_config: dict | None, service: Service,
     lock_state_at_startup: int = 1)
```

Key methods (forwarded to `Service` unless noted):
- get_lock_current_state() -> int
- get_lock_target_state() -> int
- set_lock_target_state(value: int) -> int
- get_hardware_finish() -> str (base64 TLV8)
- get_nfc_access_supported_configuration() -> str (base64 TLV8)
- get_nfc_access_control_point() -> str
- set_nfc_access_control_point(value: str) -> str
- get_configuration_state() -> int

Usage:
```python
from pyhap.accessory_driver import AccessoryDriver
from accessory import Lock

# driver created in main.configure_hap_accessory
lock = Lock(driver, "My Lock", manufacturer="Acme", serialNumber="1234",
            model="Model X", firmware="1.0.0", ha_config=None, service=service)
```

---

## home_assistant.py

### class HomeAssistant
Bridges the lock state with a Home Assistant cover entity via REST WebSocket or MQTT.

Constructor:
```python
HomeAssistant(ha_config: dict, apply_lock_state: callable)
```
- Reads fields documented in README (`connectionType`, `useSSL`, `serverAddress`, `apiToken`, `entityId`, MQTT fields…)
- Spawns a background thread to listen to state updates and calls `apply_lock_state(current_state, target_state)`.

Selected methods:
- get_cover_state_from_ha() -> str
- set_lock_state_in_ha(lock_target_state: int) -> None
- set_cover_state_in_ha(cover_state: str) -> None

---

## service.py

### class Service
Core runtime that polls NFC, performs Home Key authentication, updates repository, and bridges to HAP/Home Assistant.

Constructor:
```python
Service(
  clf: BroadcastFrameContactlessFrontend,
  repository: Repository,
  express: bool = True,
  finish: str = "silver",
  flow: str = "fast",
  throttle_polling: float = 0.15,
)
```

Important methods:
- start() / stop(): Start/stop NFC polling loop.
- update_hap_pairings(issuer_public_keys: set[bytes]) -> None
- set_nfc_access_control_point(value: str) -> str
- get_nfc_access_control_point() -> str
- get_nfc_access_supported_configuration() -> str
- get_hardware_finish() -> str
- get_configuration_state() -> int
- get_reader_key(req: ReaderKeyRequest) -> ReaderKeyResponse
- add_reader_key(req: ReaderKeyRequest) -> ReaderKeyResponse
- remove_reader_key(req: ReaderKeyRequest) -> ReaderKeyResponse

Hook:
- on_endpoint_authenticated(endpoint: Endpoint) -> None
  Called when an endpoint is successfully authenticated via NFC.

Usage:
```python
from util.bfclf import BroadcastFrameContactlessFrontend
from repository import Repository
from service import Service

clf = BroadcastFrameContactlessFrontend(path="tty:usbserial-0001:pn532", broadcast_enabled=True)
repo = Repository("homekey.json")
svc = Service(clf, repository=repo, express=True, finish="silver", flow="fast")
svc.start()
```

---

## homekey.py

Protocol-level functions for Apple Home Key.

### Exceptions
- ProtocolError

### Helper functions
- find_issuer_by_id(issuers: list[Issuer], id: bytes) -> Issuer | None
- find_endpoint_by_id_in_issuers(issuers: list[Issuer], id: bytes) -> Endpoint | None
- get_endpoints_from_issuers(issuers: list[Issuer]) -> Iterator[Endpoint]

### read_homekey(tag: ISO7816Tag, reader_identifier: bytes, reader_private_key: bytes,
                 issuers: list[Issuer], preferred_versions: Collection[bytes] | None = None,
                 flow: DigitalKeyFlow = DigitalKeyFlow.FAST,
                 transaction_code: DigitalKeyTransactionType = DigitalKeyTransactionType.UNLOCK,
                 reader_ephemeral_private_key: bytes | None = None,
                 transaction_identifier: bytes | None = None,
                 attestation_exchange_common_secret: bytes | None = None,
                 interface: Interface = Interface.CONTACTLESS,
                 key_size: int = 16) -> tuple[DigitalKeyFlow, list[Issuer], Endpoint | None]
Authenticate a tag and return the flow used, possibly updated issuers list, and an authenticated endpoint if any.

Example:
```python
from util.iso7816 import ISO7816Tag
from homekey import read_homekey

# tag: ISO7816Tag obtained from NFC frontend
dk_flow, new_issuers, endpoint = read_homekey(
    tag,
    reader_identifier=repo.get_reader_group_identifier() + repo.get_reader_identifier(),
    reader_private_key=repo.get_reader_private_key(),
    issuers=repo.get_all_issuers(),
    preferred_versions=[b"\x02\x00"],
)
```

Notes:
- Only protocol version 0x0200 is supported.
- `endpoint.last_used_at` and `endpoint.counter` are updated when present.

---

## repository.py

### class Repository
Persist and manage reader key material, issuers and endpoints in a JSON file.

Constructor:
```python
Repository(storage_file_path: str)
```

Key methods:
- get_reader_private_key() -> bytes
- set_reader_private_key(key: bytes) -> None
- get_reader_identifier() -> bytes
- set_reader_identifier(id: bytes) -> None
- get_reader_group_identifier() -> bytes
- get_all_issuers() -> list[Issuer]
- get_all_endpoints() -> list[Endpoint]
- get_endpoint_by_public_key(public_key: bytes) -> Endpoint | None
- get_endpoint_by_id(id: bytes) -> Endpoint | None
- get_issuer_by_public_key(public_key: bytes) -> Issuer | None
- get_issuer_by_id(id: bytes) -> Issuer | None
- upsert_issuer(issuer: Issuer) -> None
- upsert_issuers(issuers: list[Issuer]) -> None
- upsert_endpoint(issuer_id: bytes, endpoint: Endpoint) -> None
- remove_issuer(issuer: Issuer) -> None

---

## entity.py

Dataclasses and TLV8 models used throughout the project.

- Enums: `KeyType`, `Context`, `Interface`, `Operation`, `KeyState`, `OperationStatus`, `HardwareFinishColor`
- Dataclasses: `Enrollment`, `Enrollments`, `Endpoint`, `Issuer`
- TLV8 models: `HardwareFinishResponse`, `SupportedConfigurationResponse`,
  `DeviceCredentialRequest`, `ReaderKeyRequest`, `ControlPointRequest`,
  `DeviceCredentialResponse`, `ReaderKeyResponse`, `ControlPointResponse`

Example: build a TLV8 request to add a device credential
```python
from entity import DeviceCredentialRequest, ControlPointRequest, Operation, KeyType

req = ControlPointRequest(
    operation=Operation.ADD,
    device_credential_request=DeviceCredentialRequest(
        key_type=KeyType.SECP256R1,
        credential_public_key=bytes.fromhex("04" + "11"*64)[1:],
        issuer_key_identifier=b"\x00"*8,
    ),
)
packed = req.pack()
```

---

## util.digital_key

- DigitalKeyTransactionType: enum (UNLOCK)
- DigitalKeyTransactionFlags: enum (STANDARD, FAST)
- DigitalKeyFlow: enum (FAST, STANDARD, ATTESTATION)
- DigitalKeySecureContext
  - transceive(command) -> ISO7816Response (secure-secure)
  - encrypt_command / decrypt_command
  - encrypt_response / decrypt_response

---

## util.iso7816

- ISO7816Application: enum of AIDs
- ISO7816Instruction: common ISO7816 opcodes
- ISO7816Class: type for CLA
- ISO7816Command: APDU command pack/unpack
- ISO7816Response: APDU response pack/unpack
- ISO7816: helpers (`select_file`, `select_aid`)
- ISO7816Tag: thin wrapper that translates to/from bytes

Usage:
```python
from util.iso7816 import ISO7816, ISO7816Tag
cmd = ISO7816.select_aid(ISO7816Application.HOME_KEY)
res = ISO7816Tag(tag_impl).transceive(cmd)
```

---

## util.tlv

BER-TLV and TLV8 helpers used across protocol code.

- BERTLVTag, BERTLVLength, BERTLV, TLV8, TLV8Field, TLV8Object
- TLV8Object.unpack/pack maps to dataclass-like fields

---

## util.ecp

Build Enhanced Contactless Polling (ECP) frames.

- ECP.home(identifier: bytes, flag_2: int = 1, ...) -> ECPV2
- class ECPV2(Packable) with `pack()`

---

## util.bfclf

Broadcast-enabled Contactless Frontend backed by nfcpy with PN532/USB patches.

- class BroadcastFrameContactlessFrontend(ContactlessFrontend)
  - __init__(path: str | None, broadcast_enabled: bool = False)
  - sense(RemoteTarget(...), broadcast: bytes | None = None) -> RemoteTarget | None

Usage:
```python
from util.bfclf import BroadcastFrameContactlessFrontend, RemoteTarget
clf = BroadcastFrameContactlessFrontend(path="usb:072f:2200", broadcast_enabled=True)
rt = clf.sense(RemoteTarget("106A"), broadcast=ECP.home(identifier=group_id).pack())
```

---

## util.crypto

Helpers for AES-CBC, CMAC and EC keys.
- load_ec_public_key_from_bytes(data[, curve]) -> EllipticCurvePublicKey
- get_ec_key_public_points(key) -> tuple[bytes, bytes]
- encrypt_aes_cbc/decrypt_aes_cbc
- aes_cmac
- pad_mode_3 / unpad_mode_3

---

## util.iso18013

ISO18013 secure messaging utilities.
- class ISO18013SecureContext
  - encrypt_message_to_endpoint(message: bytes) -> bytes
  - decrypt_message_from_endpoint(message: bytes) -> bytes

---

## util.ndef

NDEF record/message packing and parsing.
- NDEFRecordType, NDEFRecord, NDEFMessage

---

## util.structable

Packing and representation helpers.
- Packable, Unpackable, pack(), represent()
- pack_into_base64_string(), unpack_from_base64_string()

---

## util.generic

Small helpers.
- chunked(source: bytes, size: int)
- get_tlv_tag(tlv_array, tag_value)
- int_to_bytes, bits

---

## util.nfc

Low-level NFC helpers.
- crc16a(data: bytes) -> bytearray
- with_crc16(data: bytes) -> bytes
- with_crc16a: alias of with_crc16

---

## util.threads

Threading helpers to run resilient background loops.
- runner(target, name: str, flag=lambda *args: True, delay=0, exception_delay=5) -> callable
- create_runner(name: str, target: callable, flag: callable, start: bool = False, **kwargs) -> threading.Thread

Usage:
```python
from util.threads import create_runner

class Worker:
    def __init__(self):
        self._run = True
    def flag(self):
        return self._run
    def do(self):
        # work here
        pass

w = Worker()
th = create_runner(name="worker", target=w.do, flag=w.flag, start=True, delay=0.1)
```

---

## Examples

### Minimal run (see README for full setup)
```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

### Reading a Home Key with a custom loop
```python
from util.bfclf import BroadcastFrameContactlessFrontend, RemoteTarget, activate
from util.ecp import ECP
from util.iso7816 import ISO7816Tag
from repository import Repository
from homekey import read_homekey

repo = Repository("homekey.json")
clf = BroadcastFrameContactlessFrontend(path="tty:usbserial-0001:pn532", broadcast_enabled=True)
clf.open(clf.path)
rt = clf.sense(RemoteTarget("106A"), broadcast=ECP.home(identifier=repo.get_reader_group_identifier()).pack())
if rt:
    tag = ISO7816Tag(activate(clf, rt))
    flow, issuers, endpoint = read_homekey(
        tag,
        reader_identifier=repo.get_reader_group_identifier() + repo.get_reader_identifier(),
        reader_private_key=repo.get_reader_private_key(),
        issuers=repo.get_all_issuers(),
        preferred_versions=[b"\x02\x00"],
    )
    if endpoint:
        print("Authenticated:", endpoint)
```