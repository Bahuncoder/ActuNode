"""The ROS 2 robot's occupancy map (ros2/map) is generated from this warehouse and kept up to date (D-51)."""

import importlib.util
from pathlib import Path

from app.warehouse import LOCATIONS, MAP_SIZE, RACKS

ROOT = Path(__file__).resolve().parents[2]


def make_map():
    spec = importlib.util.spec_from_file_location("make_map", ROOT / "ros2" / "make_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_map_files_are_up_to_date():
    module = make_map()
    for name, data in module.files().items():
        assert (ROOT / "ros2" / "map" / name).read_bytes() == data, f"run: python3 ros2/make_map.py ({name} is stale)"


def cell(cells, resolution, x, y):
    return cells[len(cells) - 1 - int(y / resolution)][int(x / resolution)]


def test_every_location_is_free_and_racks_and_walls_are_occupied():
    module = make_map()
    cells = module.grid(module.warehouse())
    assert len(cells[0]) * module.RESOLUTION == MAP_SIZE["width"]
    assert len(cells) * module.RESOLUTION == MAP_SIZE["height"]
    for name, place in LOCATIONS.items():
        assert cell(cells, module.RESOLUTION, place["x"], place["y"]) == module.FREE, name
    for rack in RACKS:
        middle = (rack["x"] + rack["w"] / 2, rack["y"] + rack["h"] / 2)
        assert cell(cells, module.RESOLUTION, *middle) == module.OCCUPIED
    assert cell(cells, module.RESOLUTION, 0.0, 10.0) == module.OCCUPIED  # outer wall
