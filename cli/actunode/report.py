"""What a run tells people (a readable log) and CI systems (JUnit XML)."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TextIO

from actunode.runner import ERROR, FAILED, PASSED, SKIPPED, ScenarioResult, StepResult

MARKS = {PASSED: "ok  ", FAILED: "FAIL", ERROR: "ERR ", SKIPPED: "skip"}
# Text from the stack (robot error types, server messages) reaches a terminal and an XML file: control
# characters (terminal escape sequences, characters XML 1.0 forbids) are shown as \\xNN instead.
_UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe(text: str) -> str:
    return _UNSAFE.sub(lambda m: f"\\x{ord(m.group()):02x}", str(text))


class Console:
    def __init__(self, out: TextIO):
        self.out = out

    def line(self, text: str = "") -> None:
        print(safe(text), file=self.out, flush=True)

    def scenario_started(self, result_name: str, path: Path) -> None:
        self.line(f"{result_name}  ({path})")

    def step(self, step: StepResult) -> None:
        self.line(f"  {MARKS[step.outcome]} {step.number:>2}. {step.text}  [{step.seconds:.1f} s]")
        if step.message:
            self.line(f"           {step.message}")

    def scenario_finished(self, result: ScenarioResult) -> None:
        if result.outcome == ERROR and not any(s.outcome != SKIPPED for s in result.steps):
            self.line(f"  ERR  {result.message}")
        for line in result.cleanup:
            self.line(f"  cleanup: {line}")
        if result.session:
            self.line(f"  recorded: session {result.session} (replay or download it in the lab)")
        if result.recording:
            self.line(f"  recording: {result.recording}")
        self.line(f"  -> {result.outcome.upper()} in {result.seconds:.1f} s")
        self.line()

    def summary(self, results: list[ScenarioResult], seconds: float) -> None:
        counts = {outcome: sum(r.outcome == outcome for r in results) for outcome in (PASSED, FAILED, ERROR)}
        self.line(
            f"{len(results)} scenario(s): {counts[PASSED]} passed, {counts[FAILED]} failed, "
            f"{counts[ERROR]} could not run  ({seconds:.1f} s)"
        )


def step_log(result: ScenarioResult) -> str:
    lines = []
    for step in result.steps:
        lines.append(f"{MARKS[step.outcome]} {step.number:>2}. {step.text}  [{step.seconds:.1f} s]")
        if step.message:
            lines.append(f"         {step.message}")
    lines += [f"cleanup: {line}" for line in result.cleanup]
    if result.session:
        lines.append(f"recorded: session {result.session}")
    if result.recording:
        lines.append(f"recording: {result.recording}")
    return safe("\n".join(lines))


def junit(results: list[ScenarioResult], seconds: float) -> bytes:
    """JUnit XML as GitHub Actions, GitLab and Jenkins read it: one test case per scenario."""
    failures = sum(r.outcome == FAILED for r in results)
    errors = sum(r.outcome == ERROR for r in results)
    attrs = {"name": "actunode", "tests": str(len(results)), "failures": str(failures), "errors": str(errors)}
    root = ET.Element("testsuites", {**attrs, "time": f"{seconds:.3f}"})
    suite = ET.SubElement(root, "testsuite", {**attrs, "skipped": "0", "time": f"{seconds:.3f}"})
    for result in results:
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": safe(result.scenario.path.stem),
                "name": safe(result.scenario.name),
                "file": safe(str(result.scenario.path)),
                "time": f"{result.seconds:.3f}",
            },
        )
        if result.session:
            properties = ET.SubElement(case, "properties")
            ET.SubElement(properties, "property", {"name": "actunode.session", "value": safe(result.session)})
        if result.outcome in (FAILED, ERROR):
            kind = "failure" if result.outcome == FAILED else "error"
            element = ET.SubElement(case, kind, {"message": safe(result.message), "type": kind})
            element.text = step_log(result)
        ET.SubElement(case, "system-out").text = step_log(result)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
