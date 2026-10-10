import os

# VDA 5050 topic layout: interfaceName/majorVersion/manufacturer/serialNumber/topic
INTERFACE_NAME = os.getenv("ACTUNODE_VDA_INTERFACE", "uagv")


def topic(manufacturer: str, serial_number: str, name: str, major: str = "v2") -> str:
    """`major` is the robot's VDA 5050 major version as written in topics ("v2", "v3")."""
    return f"{INTERFACE_NAME}/{major}/{manufacturer}/{serial_number}/{name}"


def control_topic(serial_number: str, name: str) -> str:
    """ActuNode's own simulator control channel, kept apart from VDA 5050 topics."""
    return f"actunode/v1/sim/{serial_number}/{name}"
