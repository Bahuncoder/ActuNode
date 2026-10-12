"""Named locations in the demo warehouse (meters, origin bottom-left).

Layout follows the first-customer workflow:
receiving -> storage -> pack/sort -> loading docks, with charging and a conveyor.
"""

LOCATIONS: dict[str, dict] = {
    "CHARGING": {"x": 11.0, "y": 2.2, "zone": "charging"},
    "RECEIVING_DOOR_1": {"x": 2.0, "y": 18.0, "zone": "receiving"},
    "RECEIVING_DOOR_2": {"x": 2.0, "y": 14.0, "zone": "receiving"},
    "STORAGE_A17": {"x": 14.0, "y": 18.0, "zone": "storage"},
    "STORAGE_B04": {"x": 18.0, "y": 12.0, "zone": "storage"},
    "PACK_SORT": {"x": 28.0, "y": 15.0, "zone": "pack_sort"},
    "CONVEYOR": {"x": 24.0, "y": 4.0, "zone": "conveyor"},
    "LOADING_DOCK_1": {"x": 38.0, "y": 18.0, "zone": "loading"},
    "LOADING_DOCK_2": {"x": 38.0, "y": 12.0, "zone": "loading"},
}

MAP_SIZE = {"width": 40, "height": 20}

ZONES: list[dict] = [
    {"id": "receiving", "label": "RECEIVING", "x": 0, "y": 11, "w": 5, "h": 9},
    {"id": "storage", "label": "STORAGE RACKS", "x": 9, "y": 9, "w": 12, "h": 11},
    {"id": "pack_sort", "label": "PACK / SORT", "x": 25, "y": 11, "w": 6, "h": 8},
    {"id": "loading", "label": "LOADING DOCKS", "x": 35, "y": 9, "w": 5, "h": 11},
    {"id": "charging", "label": "CHARGING", "x": 0, "y": 0, "w": 12, "h": 4},
    {"id": "conveyor", "label": "CONVEYOR", "x": 14, "y": 3, "w": 20, "h": 2},
    # Robots that do not fit the charging area wait here.
    {"id": "parking", "label": "PARKING", "x": 0, "y": 5, "w": 8.5, "h": 5.5},
]

# Rack rows run along x 10-20, centered on these y values, 0.8 m thick.
RACK_ROWS = [11, 13.5, 16, 18.5]
RACKS: list[dict] = [{"x": 10, "y": y - 0.4, "w": 10, "h": 0.8} for y in RACK_ROWS]
