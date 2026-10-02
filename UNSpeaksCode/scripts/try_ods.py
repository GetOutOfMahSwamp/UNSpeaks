"""Try the ODS download layer by hand (step 2: no MCP yet).

Run from the UNSpeaksCode folder:

    uv run python scripts/try_ods.py A/RES/78/1
    uv run python scripts/try_ods.py "S/RES/2720(2023)" --pages 1-2
    uv run python scripts/try_ods.py A/RES/78/1 --language fr

The first run downloads the PDF, and later runs read it from the cache in
data/cache/ods/. Each request respects the Library's limit (100 per 5 minutes).
"""

from __future__ import annotations

import argparse
import sys

from unspeaks.ods_client import OdsClient, OdsError
from unspeaks.pdf_text import load_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one UN document from ODS.")
    parser.add_argument("symbol", help="document symbol, e.g. A/RES/78/1")
    parser.add_argument("--language", default="en", help="ar, zh, en, fr, ru or es (default: en)")
    parser.add_argument("--pages", default="1", help="page or range to print, e.g. 1 or 2-3")
    parser.add_argument("--max-chars", type=int, default=1500, help="characters to print per page")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")  # don't crash on characters the console can't show
    except AttributeError:
        pass

    with OdsClient() as client:
        try:
            fetched = client.fetch_pdf(args.symbol, args.language)
        except OdsError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    pages = load_pages(fetched.path)
    print(f"Symbol:      {fetched.symbol} ({fetched.language})")
    print(f"Source:      {fetched.source_url}")
    print(f"Downloaded:  {fetched.fetched_at}  (from cache: {fetched.from_cache})")
    print(f"Cached at:   {fetched.path}")
    print(f"Pages:       {len(pages)}")

    first, _, last = args.pages.partition("-")
    start = max(1, int(first))
    end = min(len(pages), int(last or first))
    for number in range(start, end + 1):
        text = pages[number - 1]
        shown = text[: args.max_chars] + (" [...]" if len(text) > args.max_chars else "")
        print(f"\n----- page {number} of {len(pages)} -----\n{shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
