"""`python -m app.demo build`: rebuild the demo database (used by `make demo`).
`python -m app.demo bundle`: the read-only demo bundle a Vercel deploy starts from
(backend/deploy/: demo-data/ and a copy of data/seed/; used by `make vercel-bundle`)."""

import shutil
import sys

from app.core.config import REPO_ROOT, Settings, get_settings
from app.demo.build import build

DEPLOY = REPO_ROOT / "backend" / "deploy"


def _force_writable(function: object, path: str, _exc: object) -> None:
    import os
    import stat

    os.chmod(path, stat.S_IWRITE)  # landing files are read-only by design
    function(path)  # type: ignore[operator]


def bundle() -> None:
    data = DEPLOY / "demo-data"
    if DEPLOY.exists():
        shutil.rmtree(DEPLOY, onerror=_force_writable)
    settings = Settings(
        data_dir=data,
        database_url=f"sqlite:///{(data / 'demo.db').as_posix()}",
        demo_mode=True,
    )
    print(f"Building the Vercel demo bundle in {DEPLOY}")
    build(settings)
    # Only what a cold start needs: the database, the feed files and the state.
    shutil.rmtree(data / "landing", onerror=_force_writable)
    for extra in ("pristine.db", "demo.db-wal", "demo.db-shm"):
        (data / extra).unlink(missing_ok=True)
    shutil.copytree(REPO_ROOT / "data" / "seed", DEPLOY / "seed")
    size = sum(p.stat().st_size for p in DEPLOY.rglob("*") if p.is_file())
    print(f"Bundle ready: {size / 1e6:.1f} MB")


def main(argv: list[str]) -> int:
    command = argv[:1]
    if command == ["build"]:
        settings = get_settings()
        print(f"Building the demo database in {settings.data_dir}")
        build(settings)
        return 0
    if command == ["bundle"]:
        bundle()
        return 0
    print("usage: python -m app.demo build | bundle")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
