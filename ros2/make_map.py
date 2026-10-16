"""Write the Nav2 occupancy map of ActuNode's demo warehouse (D-51): ros2/map/warehouse.pgm and .yaml.

    python3 ros2/make_map.py            (from the repo root; standard library only)

The map is generated from backend/app/warehouse.py, so a location's coordinates mean the same to the ROS 2
robot as to ActuNode: origin at the warehouse's bottom-left corner, metres, x right, y up. Racks and the outer
walls are obstacles; everything else is free. backend/tests/test_ros2_map.py checks the committed files are
up to date.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLUTION = 0.1  # metres per cell
FREE, OCCUPIED = 254, 0  # PGM grey levels Nav2 reads as free / occupied (negate: 0)


def warehouse():
    spec = importlib.util.spec_from_file_location("warehouse", ROOT / "backend" / "app" / "warehouse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grid(module) -> list[list[int]]:
    """Rows top to bottom, as PGM stores them (row 0 is the largest y)."""
    width = round(module.MAP_SIZE["width"] / RESOLUTION)
    height = round(module.MAP_SIZE["height"] / RESOLUTION)
    cells = [[FREE] * width for _ in range(height)]

    def block(x: float, y: float, w: float, h: float) -> None:
        for column in range(max(0, int(x / RESOLUTION)), min(width, round((x + w) / RESOLUTION))):
            for row in range(max(0, int(y / RESOLUTION)), min(height, round((y + h) / RESOLUTION))):
                cells[height - 1 - row][column] = OCCUPIED

    for rack in module.RACKS:
        block(rack["x"], rack["y"], rack["w"], rack["h"])
    for row in (0, height - 1):  # outer walls, one cell thick
        cells[row] = [OCCUPIED] * width
    for line in cells:
        line[0] = line[-1] = OCCUPIED
    return cells


def pgm(cells: list[list[int]]) -> bytes:
    header = f"P5\n# ActuNode demo warehouse (ros2/make_map.py)\n{len(cells[0])} {len(cells)}\n255\n".encode()
    return header + bytes(value for line in cells for value in line)


YAML = """image: warehouse.pgm
mode: trinary
resolution: {resolution}
origin: [0.0, 0.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.25
"""


def files() -> dict[str, bytes]:
    return {
        "warehouse.pgm": pgm(grid(warehouse())),
        "warehouse.yaml": YAML.format(resolution=RESOLUTION).encode(),
    }


def main() -> int:
    out = ROOT / "ros2" / "map"
    out.mkdir(exist_ok=True)
    for name, data in files().items():
        (out / name).write_bytes(data)
        print(f"wrote {out / name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
