"""Startup storage migration for the v0.5.0 runtime layout."""

from __future__ import annotations

import errno
import filecmp
import logging
import os
import shutil
import sys
from pathlib import Path

try:
    from backend import runtime_paths
except Exception:
    import runtime_paths  # type: ignore


log = logging.getLogger("storage_migration")


class StorageMigrationError(RuntimeError):
    """Raised when migration cannot continue safely."""


def _move_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copy2(src, dst)
        os.remove(src)


def _chmod_secrets(path: Path) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        log.warning("[MIGRATION] warning: unable to chmod %s: %s", path, exc)


def run_storage_migration(paths) -> None:
    """Move legacy runtime files into the canonical v0.5.0 layout."""

    for directory in (paths.DATA_DIR, paths.CONF_DIR, paths.TMP_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)

    migrations = tuple(paths.LEGACY_MIGRATIONS)
    if not any(Path(item.source).exists() for item in migrations):
        _chmod_secrets(Path(paths.SECRETS_FILE))
        return

    log.info("[MIGRATION] start")

    for item in migrations:
        src = Path(item.source)
        dst = Path(item.destination)
        if src.exists() and dst.exists() and not filecmp.cmp(src, dst, shallow=False):
            log.error("[MIGRATION] conflict detected: %s and %s differ", src, dst)
            log.error("[MIGRATION] aborted")
            raise StorageMigrationError(f"Storage migration conflict: {src} and {dst} differ")

    for item in migrations:
        src = Path(item.source)
        dst = Path(item.destination)
        src_exists = src.exists()
        dst_exists = dst.exists()

        if src_exists and dst_exists:
            log.info("[MIGRATION] remove legacy %s", src)
            os.remove(src)
            continue

        if src_exists:
            log.info("[MIGRATION] move %s -> %s", src, dst)
            _move_file(src, dst)

    for item in migrations:
        src = Path(item.source)
        dst = Path(item.destination)
        if src.exists() and dst.exists() and filecmp.cmp(src, dst, shallow=False):
            log.info("[MIGRATION] remove legacy %s", src)
            os.remove(src)

    _chmod_secrets(Path(paths.SECRETS_FILE))
    log.info("[MIGRATION] done")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run_storage_migration(runtime_paths)
    except Exception:
        log.exception("[MIGRATION] failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
