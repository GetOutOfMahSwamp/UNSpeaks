"""Build the local UNSpeaks database from the datasets in data/raw/.

    uv run unspeaks-build-db

Run it again whenever you download a newer version of a dataset. The database is
written to data/unspeaks.sqlite (not in Git).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from unspeaks import config
from unspeaks.sources import undl
from unspeaks.votes.store import VoteWriter


def build(raw_dir: Path, output: Path, log=print) -> dict:
    """Build into a temporary file first, so a failed build never breaks a working database."""
    temporary = output.with_name(output.name + ".building")
    with VoteWriter.create(temporary) as writer:
        writer.add_meta("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        summary = undl.load(writer, raw_dir, log)
    if not summary:
        temporary.unlink(missing_ok=True)
        return summary
    temporary.replace(output)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the UNSpeaks database from data/raw/.")
    parser.add_argument("--raw-dir", type=Path, default=config.data_dir() / "raw")
    parser.add_argument("--output", type=Path, default=config.database_path())
    args = parser.parse_args(argv)

    started = time.monotonic()
    print(f"Datasets folder: {args.raw_dir}")
    summary = build(args.raw_dir, args.output)
    if not summary:
        print(
            "No datasets found. Download them from the UN Digital Library (see the README, "
            "'Data sources') and save them in the datasets folder, keeping their file names.",
            file=sys.stderr,
        )
        return 1
    for name, count in summary.items():
        print(f"  {name.replace('_', ' '):<16} {count:>9,}")
    size_mb = args.output.stat().st_size / 1_000_000
    print(f"Done in {time.monotonic() - started:.0f} s: {args.output} ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
