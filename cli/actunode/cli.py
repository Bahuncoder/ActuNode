"""actunode test [PATH ...]: run scenario files against a running ActuNode stack (D-45).

Exit codes: 0 every scenario passed; 1 at least one failed; 2 a scenario file or the command line is not
valid (nothing was run); 3 at least one scenario could not run (stack unreachable, login refused, robots
offline). CI can tell "the integration broke" (1) from "the test environment broke" (3).
"""

import argparse
import os
import sys
import time
from pathlib import Path

from actunode import __version__
from actunode.capture import MAX_SESSION_BYTES, ImportError_, convert
from actunode.client import DEFAULT_URL, Stack, StackError, read_token
from actunode.report import Console, junit, safe
from actunode.runner import ERROR, FAILED, Runner
from actunode.scenario import ScenarioError, find, load

EXIT_PASSED, EXIT_FAILED, EXIT_INVALID, EXIT_ERROR, EXIT_INTERRUPTED = 0, 1, 2, 3, 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="actunode", description="ActuNode scenario tests.")
    parser.add_argument("--version", action="version", version=f"actunode {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser(
        "test",
        help="run scenario files against a running stack",
        description="Run scenario files (or every *.yaml / *.yml in a directory) against a running ActuNode stack.",
        epilog="Exit codes: 0 passed, 1 failed, 2 invalid scenario or arguments, 3 could not run.",
    )
    test.add_argument("paths", nargs="+", type=Path, metavar="PATH", help="scenario file or directory")
    test.add_argument(
        "--url",
        default=os.environ.get("ACTUNODE_URL", DEFAULT_URL),
        help=f"the stack's web address (default: $ACTUNODE_URL or {DEFAULT_URL})",
    )
    test.add_argument(
        "--token-file",
        type=Path,
        default=Path(os.environ["ACTUNODE_TOKEN_FILE"]) if os.environ.get("ACTUNODE_TOKEN_FILE") else None,
        help="file holding the API token, if the stack requires login ($ACTUNODE_TOKEN_FILE, or $ACTUNODE_TOKEN)",
    )
    test.add_argument("--ca-file", type=Path, help="CA certificate to trust for an https:// stack with its own CA")
    test.add_argument("--vda-version", choices=("2", "3"), help="address robots of this VDA 5050 major version")
    test.add_argument("--junit", type=Path, metavar="FILE", help="also write a JUnit XML report to FILE")
    test.add_argument("--dry-run", action="store_true", help="check the scenario files and list their steps only")
    test.add_argument(
        "--no-record", action="store_true", help="do not record each scenario run as a session in the lab"
    )
    test.add_argument(
        "--no-cleanup", action="store_true", help="leave injected failures and running missions as they are"
    )
    imp = commands.add_parser(
        "import",
        help="turn a mosquitto_sub capture into a session file",
        description="Turn a capture made with  mosquitto_sub -t 'uagv/#' -F '%%U %%t %%p'  into a session file "
        "for the lab (upload, validate, replay). Offline: nothing connects anywhere.",
        epilog="Exit codes: 0 written, 2 unusable input or arguments.",
    )
    imp.add_argument("capture", metavar="CAPTURE", help="the capture file, or - for standard input")
    imp.add_argument("-o", "--output", type=Path, required=True, help="session file to write (.jsonl)")
    imp.add_argument("--name", help="name in the session id (letters, digits, - and _)")
    imp.add_argument("--strict", action="store_true", help="fail on the first line that cannot be read")
    imp.add_argument("--force", action="store_true", help="overwrite OUTPUT if it exists")
    return parser


def _import(args, console: Console, stdin) -> int:
    try:
        source = stdin if args.capture == "-" else open(args.capture, "rb")  # noqa: SIM115
    except OSError as error:
        console.line(f"error: cannot read {args.capture}: {error.strerror or error}")
        return EXIT_INVALID
    try:
        stats = convert(source, args.output, args.name, strict=args.strict, force=args.force)
    except ImportError_ as error:
        console.line(f"error: {error}")
        return EXIT_INVALID
    finally:
        if source is not stdin:
            source.close()
    console.line(f"{stats['messages']} message(s) written to {args.output}  (session {stats['sessionId']})")
    console.line(f"time span: {stats['seconds']:.3f} s, {stats['firstAt']} to {stats['lastAt']}")
    robots = sorted(stats["robots"])
    more = " and more" if stats["moreRobots"] else ""
    console.line(
        f"robots seen: {len(robots)}"
        + (f" ({', '.join(robots[:10])}{', ...' if len(robots) > 10 else ''}{more})" if robots else "")
    )
    if stats["skipped"]:
        lines = ", ".join(map(str, stats["badLines"]))
        console.line(f"skipped {stats['skipped']} line(s) that could not be read (first: {lines})")
    if stats["backwards"]:
        console.line(f"{stats['backwards']} timestamp(s) went backwards; their time was held at the previous message")
    if stats["bytes"] > MAX_SESSION_BYTES:
        console.line(f"warning: {stats['bytes']} bytes is over the default upload limit of {MAX_SESSION_BYTES}")
    console.line("next: upload it in the lab (Sessions, Upload) or POST /api/sessions/upload")
    return EXIT_PASSED


def _write(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as error:
        raise StackError(f"cannot write {path}: {error.strerror or error}") from None


def main(argv: list[str] | None = None, out=None, stack_factory=Stack, stdin=None) -> int:
    out = out or sys.stdout
    args = _parser().parse_args(argv)
    console = Console(out)
    if args.command == "import":
        return _import(args, console, stdin or sys.stdin.buffer)

    files = find(args.paths)
    scenarios, invalid = [], False
    for path in files:
        try:
            scenarios.append(load(path))
        except ScenarioError as error:
            invalid = True
            console.line(f"{path}: invalid scenario")
            for line in str(error).splitlines():
                console.line(f"  {line}")
    if not files:
        console.line("no scenario files found (*.yaml, *.yml)")
        return EXIT_INVALID
    if invalid:
        return EXIT_INVALID

    if args.dry_run:
        for scenario in scenarios:
            console.line(f"{scenario.name}  ({scenario.path})")
            for number, step in enumerate(scenario.steps, start=1):
                console.line(f"       {number:>2}. {step.describe()}")
        console.line(f"{len(scenarios)} valid scenario(s)")
        return EXIT_PASSED

    started = time.monotonic()
    try:
        stack = stack_factory(args.url, token=read_token(args.token_file), ca_file=args.ca_file)
    except StackError as error:
        console.line(f"error: {error}")
        return EXIT_ERROR

    results = []
    try:
        try:
            health = stack.connect()
            console.line(f"ActuNode {safe(health.get('version', '?'))} at {args.url}\n")
        except StackError as error:
            console.line(f"error: {error}")
            return EXIT_ERROR
        runner = Runner(
            stack,
            vda_version=args.vda_version,
            cleanup=not args.no_cleanup,
            record=not args.no_record,
            on_step=console.step,
        )
        for scenario in scenarios:
            console.scenario_started(scenario.name, scenario.path)
            result = runner.run(scenario)
            console.scenario_finished(result)
            results.append(result)
    except KeyboardInterrupt:
        cleaned = "left as they were" if args.no_cleanup else "cleaned up"
        console.line(f"\ninterrupted (injected failures and running missions were {cleaned})")
        return EXIT_INTERRUPTED
    finally:
        stack.close()

    seconds = time.monotonic() - started
    console.summary(results, seconds)
    if args.junit:
        try:
            _write(args.junit, junit(results, seconds))
        except StackError as error:
            console.line(f"error: {error}")
            return EXIT_ERROR
    if any(r.outcome == ERROR for r in results):
        return EXIT_ERROR
    if any(r.outcome == FAILED for r in results):
        return EXIT_FAILED
    return EXIT_PASSED
