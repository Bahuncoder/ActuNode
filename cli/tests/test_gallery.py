"""docs/SCENARIO_GALLERY.md lists every scenario that ships with ActuNode, and every listed file is valid (D-53)."""

from pathlib import Path

from actunode.scenario import find, load

ROOT = Path(__file__).resolve().parents[2]
FOLDERS = ("scenarios", "examples/fleet_manager", "conformance")  # examples/ci holds a CI workflow, not scenarios


def shipped() -> list[Path]:
    return find([ROOT / folder for folder in FOLDERS])


def test_every_shipped_scenario_is_in_the_gallery_and_valid():
    gallery = (ROOT / "docs" / "SCENARIO_GALLERY.md").read_text()
    files = shipped()
    assert len(files) >= 16
    for path in files:
        load(path)  # raises on an invalid file
        assert f"](../{path.relative_to(ROOT).as_posix()})" in gallery, f"{path.relative_to(ROOT)} not in the gallery"
