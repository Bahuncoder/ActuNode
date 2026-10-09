import os

# VDA 5050 topic layout: interfaceName/majorVersion/manufacturer/serialNumber/topic
INTERFACE_NAME = os.getenv("ACTUNODE_VDA_INTERFACE", "uagv")
MAJOR_VERSION = os.getenv("ACTUNODE_VDA_MAJOR_VERSION", "v2")


def topic(manufacturer: str, serial_number: str, name: str) -> str:
    return f"{INTERFACE_NAME}/{MAJOR_VERSION}/{manufacturer}/{serial_number}/{name}"
