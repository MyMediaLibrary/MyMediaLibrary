"""Pure helpers to build the future library_inventory document structures.

This module is intentionally side-effect free and not wired into runtime scanning yet.
"""

from __future__ import annotations

import copy
from typing import Any


def build_inventory_id(media_type: str, category: str, root_folder_name: str) -> str:
    """Build stable root-level inventory id: type:category:root_folder_name."""
    return f"{media_type}:{category}:{root_folder_name}"


def build_inventory_video_file(
    name: str,
    first_seen_at: str,
    last_seen_at: str,
    status: str = "present",
) -> dict[str, str]:
    """Build one inventory video file object."""
    return {
        "name": name,
        "status": status,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
    }


def build_inventory_subfolder(
    name: str,
    video_files: list[dict[str, str]],
    first_seen_at: str,
    last_seen_at: str,
    status: str = "present",
) -> dict[str, Any]:
    """Build one inventory subfolder object."""
    return {
        "name": name,
        "status": status,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "video_files": list(video_files),
    }


def build_inventory_movie_item(
    category: str,
    title: str,
    root_folder_name: str,
    root_folder_path: str,
    video_files: list[dict[str, str]],
    first_seen_at: str,
    last_seen_at: str,
    status: str = "present",
) -> dict[str, Any]:
    """Build one root inventory item for a movie."""
    return {
        "id": build_inventory_id("movie", category, root_folder_name),
        "media_type": "movie",
        "category": category,
        "title": title,
        "root_folder_path": root_folder_path,
        "status": status,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "video_files": list(video_files),
    }


def build_inventory_tv_item(
    category: str,
    title: str,
    root_folder_name: str,
    root_folder_path: str,
    first_seen_at: str,
    last_seen_at: str,
    video_files: list[dict[str, str]] | None = None,
    subfolders: list[dict[str, Any]] | None = None,
    status: str = "present",
) -> dict[str, Any]:
    """Build one root inventory item for a TV show."""
    return {
        "id": build_inventory_id("tv", category, root_folder_name),
        "media_type": "tv",
        "category": category,
        "title": title,
        "root_folder_path": root_folder_path,
        "status": status,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "video_files": list(video_files or []),
        "subfolders": list(subfolders or []),
    }


def build_inventory_document(
    items: list[dict[str, Any]],
    generated_at: str,
    scan_mode: str,
    missing_reconciliation: bool,
    version: int = 1,
) -> dict[str, Any]:
    """Build full inventory document shape."""
    return {
        "version": version,
        "generated_at": generated_at,
        "scan_mode": scan_mode,
        "missing_reconciliation": missing_reconciliation,
        "items": [copy.deepcopy(item) for item in items],
    }
