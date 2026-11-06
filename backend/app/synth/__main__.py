"""`make synth`: regenerate data/raw/ from the fixed seed."""

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.synth.generate import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.synth")
    parser.add_argument("--out", type=Path, default=get_settings().raw_dir)
    args = parser.parse_args(argv)

    manifest = generate(args.out)
    by_feed: dict[str, int] = {}
    for entry in manifest["files"]:
        by_feed[entry["feed"]] = by_feed.get(entry["feed"], 0) + entry["rows"]
    print(f"Wrote {len(manifest['files'])} files to {args.out}")
    for feed, rows in sorted(by_feed.items()):
        print(f"  {feed:<12} {rows:>5} records")
    planted = sum(1 for i in manifest["imperfections"] if i["hero_members"])
    print(f"  imperfections planted: {planted} (I-01..I-17)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
