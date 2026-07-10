"""``argo-anywhere`` console-script entry point (thin).

P0 skeleton scope: this wires the two globally-meaningful flags that need no
engine/driver -- ``--version`` and ``--print-script`` (the D-026 inspect-and-fork
escape hatch). The real subcommand surface (connect / configure / run / status /
...) routes through the two-lane driver (``driver.py``) in a later P0 step; until
then, any other invocation prints an honest "not yet wired" notice rather than
silently doing nothing.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from ._engine import ENGINE_FILENAME, engine_bytes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argo-anywhere",
        description=(
            "Run AI coding CLIs against the ANL Argo gateway from anywhere. "
            "Python runtime wrapping the bash engine (Model A; PLAN.md D-026)."
        ),
        add_help=True,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"argo-anywhere {__version__}",
        help="Print the package version and exit.",
    )
    parser.add_argument(
        "--print-script",
        action="store_true",
        help=(
            "Write the raw vendored bash engine to stdout and exit "
            f"(inspect-and-fork; e.g. `argo-anywhere --print-script > {ENGINE_FILENAME}`)."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args, rest = parser.parse_known_args(argv)

    if args.print_script:
        # Raw bytes so redirecting to a file reproduces the engine exactly.
        sys.stdout.buffer.write(engine_bytes())
        sys.stdout.buffer.flush()
        return 0

    # No recognized flag: the driver/verb surface is not wired yet (P0 skeleton).
    prog = parser.prog
    print(
        f"{prog}: the command surface is not wired yet (P0 skeleton).\n"
        f"  Available now: `{prog} --version`, `{prog} --print-script`.\n"
        f"  The connect/configure/run verbs route through the two-lane driver,\n"
        f"  landing in a later P0 step (PLAN.md D-026; spike/HANDOFF.md).",
        file=sys.stderr,
    )
    if rest:
        print(f"  (ignored args: {' '.join(rest)})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
