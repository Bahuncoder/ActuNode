from fastapi.testclient import TestClient

from app.main import app
from app.warehouse import LOCATIONS, MAP_SIZE, RACKS, ZONES


def _inside(outer, x, y):
    return outer["x"] <= x <= outer["x"] + outer["w"] and outer["y"] <= y <= outer["y"] + outer["h"]


def _overlap(a, b):
    return (
        a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]
    )


def test_every_location_is_inside_the_map_and_its_named_zone():
    zones = {z["id"]: z for z in ZONES}
    for name, loc in LOCATIONS.items():
        assert 0 <= loc["x"] <= MAP_SIZE["width"] and 0 <= loc["y"] <= MAP_SIZE["height"], name
        assert _inside(zones[loc["zone"]], loc["x"], loc["y"]), name


def test_zones_are_inside_the_map_and_do_not_overlap():
    for zone in ZONES:
        assert _inside(
            {"x": 0, "y": 0, "w": MAP_SIZE["width"], "h": MAP_SIZE["height"]},
            zone["x"] + zone["w"],
            zone["y"] + zone["h"],
        )
    for index, a in enumerate(ZONES):
        for b in ZONES[index + 1 :]:
            assert not _overlap(a, b), (a["id"], b["id"])


def test_parking_exists_and_is_clear_of_racks():
    parking = next(z for z in ZONES if z["id"] == "parking")
    assert (parking["x"], parking["y"], parking["w"], parking["h"]) == (0, 5, 8.5, 5.5)
    assert not any(_overlap(parking, rack) for rack in RACKS)


def test_racks_are_inside_the_storage_zone():
    storage = next(z for z in ZONES if z["id"] == "storage")
    assert len(RACKS) == 4
    for rack in RACKS:
        assert _inside(storage, rack["x"], rack["y"]) and _inside(storage, rack["x"] + rack["w"], rack["y"] + rack["h"])


def test_map_endpoint_serves_the_one_definition():
    client = TestClient(app, headers={"host": "localhost"})
    body = client.get("/api/map").json()
    assert body == {"size": MAP_SIZE, "zones": ZONES, "racks": RACKS, "locations": LOCATIONS}
    assert client.get("/api/locations").json() == LOCATIONS
