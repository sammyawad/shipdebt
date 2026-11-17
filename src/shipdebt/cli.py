from __future__ import annotations

import argparse
import sys

from . import __version__
from .asks import find_asks
from .report import to_json, to_text, totals
from .scan import scan


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="shipdebt",
        description="Find finished work that never shipped: commits on no remote, "
                    "branches never merged, dirty checkouts, and open 'needs a human' "
                    "asks in handoff notes. Read-only.")
    p.add_argument("roots", nargs="*", default=["."], help="folders to scan (default: .)")
    p.add_argument("--depth", type=int, default=5, help="how deep to look for repos (default 5)")
    p.add_argument("--asks", action="store_true",
                   help="also collect open human asks (NEEDS <NAME>, 'ready to deploy', ...) from .md/.txt notes")
    p.add_argument("--ask-root", action="append", default=[],
                   help="extra folder to search for asks (implies --asks); repeatable")
    p.add_argument("--ask-pattern", action="append", default=[],
                   help="regex for an ask line; replaces the built-in patterns; repeatable")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="machine-readable output")
    fmt.add_argument("--md", action="store_true", help="Markdown output (for PR comments, notes)")
    p.add_argument("--top", type=int, default=15, help="rows per list (default 15)")
    p.add_argument("--fail-over", type=int, default=None, metavar="N",
                   help="exit 2 when more than N commits are on no remote (for CI / cron)")
    p.add_argument("--version", action="version", version=f"shipdebt {__version__}")
    args = p.parse_args(argv)

    repos = scan(args.roots, max_depth=args.depth)
    asks = dupes = None
    if args.asks or args.ask_root or args.ask_pattern:
        asks, dupes = find_asks(args.roots + args.ask_root, args.ask_pattern or None)

    if args.json:
        print(to_json(repos, asks, dupes or 0))
    else:
        print(to_text(repos, asks, dupes or 0, top=args.top, markdown=args.md))

    if args.fail_over is not None and totals(repos, None)["at_risk_commits"] > args.fail_over:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
