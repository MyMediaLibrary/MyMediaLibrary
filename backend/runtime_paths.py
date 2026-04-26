"""Canonical runtime paths for MyMediaLibrary.

This module is the single source of truth for v0.5.0 storage layout paths.
Legacy paths are declared here only so the startup migration can reason about
them explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DATA_DIR = Path("/data")
CONF_DIR = Path("/conf")
TMP_DIR = Path("/tmp")
LIBRARY_DIR = Path("/library")
APP_DIR = Path("/app")

LIBRARY_JSON = DATA_DIR / "library.json"
LIBRARY_PROBE_JSON = DATA_DIR / "library_probe.json"
INVENTORY_JSON = DATA_DIR / "library_inventory.json"
RECOMMENDATIONS_JSON = DATA_DIR / "recommendations.json"
SCANNER_LOG = DATA_DIR / "scanner.log"

CONFIG_JSON = CONF_DIR / "config.json"
PROVIDERS_MAPPING_JSON = CONF_DIR / "providers_mapping.json"
PROVIDERS_LOGO_JSON = CONF_DIR / "providers_logo.json"
RECOMMENDATIONS_RULES_JSON = CONF_DIR / "recommendations_rules.json"
SECRETS_FILE = CONF_DIR / ".secrets"

SCAN_LOCK = TMP_DIR / "scan.lock"

DEFAULT_CONF_DIR = APP_DIR / "defaults" / "conf"
DEFAULT_CONFIG_JSON = DEFAULT_CONF_DIR / "config.json"
DEFAULT_PROVIDERS_MAPPING_JSON = DEFAULT_CONF_DIR / "providers_mapping.json"
DEFAULT_PROVIDERS_LOGO_JSON = DEFAULT_CONF_DIR / "providers_logo.json"
DEFAULT_RECOMMENDATIONS_RULES_JSON = DEFAULT_CONF_DIR / "recommendations_rules.json"

MIGRATION_WORK_DIR = DATA_DIR / ".migration"


@dataclass(frozen=True)
class RuntimeFile:
    """A runtime file and its optional bundled default."""

    path: Path
    default_path: Path | None = None


@dataclass(frozen=True)
class LegacyMigration:
    """A legacy source that must move to a canonical destination."""

    source: Path
    destination: Path


GENERATED_FILES = (
    LIBRARY_JSON,
    LIBRARY_PROBE_JSON,
    INVENTORY_JSON,
    RECOMMENDATIONS_JSON,
    SCANNER_LOG,
)

CONFIG_FILES = (
    RuntimeFile(CONFIG_JSON, DEFAULT_CONFIG_JSON),
    RuntimeFile(PROVIDERS_MAPPING_JSON, DEFAULT_PROVIDERS_MAPPING_JSON),
    RuntimeFile(PROVIDERS_LOGO_JSON, DEFAULT_PROVIDERS_LOGO_JSON),
    RuntimeFile(RECOMMENDATIONS_RULES_JSON, DEFAULT_RECOMMENDATIONS_RULES_JSON),
    RuntimeFile(SECRETS_FILE),
)

LEGACY_MIGRATIONS = (
    LegacyMigration(DATA_DIR / "config.json", CONFIG_JSON),
    LegacyMigration(DATA_DIR / "providers_mapping.json", PROVIDERS_MAPPING_JSON),
    LegacyMigration(DATA_DIR / "providers_logo.json", PROVIDERS_LOGO_JSON),
    LegacyMigration(DATA_DIR / "recommendations_rules.json", RECOMMENDATIONS_RULES_JSON),
    LegacyMigration(APP_DIR / ".secrets", SECRETS_FILE),
)
