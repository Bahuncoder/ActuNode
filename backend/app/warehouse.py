"""Named locations in the demo warehouse (meters, origin bottom-left).

Layout follows the first-customer workflow:
receiving -> storage -> pack/sort -> loading docks, with charging and a conveyor.
"""

LOCATIONS: dict[str, dict] = {
    "CHARGING": {"x": 3.5, "y": 2.0, "zone": "charging"},
    "RECEIVING_DOOR_1": {"x": 2.0, "y": 18.0, "zone": "receiving"},
    "RECEIVING_DOOR_2": {"x": 2.0, "y": 14.0, "zone": "receiving"},
    "STORAGE_A17": {"x": 14.0, "y": 18.0, "zone": "storage"},
    "STORAGE_B04": {"x": 18.0, "y": 12.0, "zone": "storage"},
    "PACK_SORT": {"x": 28.0, "y": 15.0, "zone": "pack_sort"},
    "CONVEYOR": {"x": 24.0, "y": 4.0, "zone": "conveyor"},
    "LOADING_DOCK_1": {"x": 38.0, "y": 18.0, "zone": "loading"},
    "LOADING_DOCK_2": {"x": 38.0, "y": 12.0, "zone": "loading"},
}
