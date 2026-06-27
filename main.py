"""Codebase Cartographer — CLI entry point.

Usage:
    python -m cartographer.main /path/to/repo
    python -m cartographer.main /path/to/repo -o onboarding.md --quiet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents import ONBOARDING_BRIEF, build_cartographer
from .tools import set_output_dir, set_repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map an unfamiliar codebase for onboarding.")
    parser.add_argument("repo", help="Path to the git repository to analyze.")
    parser.add_argument("-o", "--output", default="ONBOARDING.md",
                        help="Markdown report filename, written inside the output dir "
                             "(default: ONBOARDING.md).")
    parser.add_argument("-d", "--out-dir", dest="out_dir", default=None,
                        help="Directory for all generated files (report + diagram). "
                             "Default: a folder named after the repo, in the current dir.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Reduce agent logging.")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 2
    if not (repo / ".git").exists():
        print(f"warning: {repo} has no .git — history tools will return errors.", file=sys.stderr)

    # All artifacts land in a directory named after the repo (overridable with -d),
    # keeping them OUT of the code under analysis.
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (Path.cwd() / repo.name)

    # Point every tool at this repo and its output dir, then run the agent team.
    set_repo_root(repo)
    set_output_dir(out_dir)
    cartographer = build_cartographer(verbosity_level=0 if args.quiet else 1)

    print(f"Mapping {repo} ...\n", file=sys.stderr)
    report = cartographer.run(ONBOARDING_BRIEF)

    report_path = out_dir / args.output
    report_path.write_text(str(report), encoding="utf-8")
    print(f"\nWrote onboarding map to {report_path}", file=sys.stderr)
    print(f"Artifacts directory: {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
