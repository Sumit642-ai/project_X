"""`python -m app.demo build`: rebuild the demo database (used by `make demo`)."""

import sys

from app.core.config import get_settings
from app.demo.build import build


def main(argv: list[str]) -> int:
    if argv[:1] != ["build"]:
        print("usage: python -m app.demo build")
        return 2
    settings = get_settings()
    print(f"Building the demo database in {settings.data_dir}")
    build(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
