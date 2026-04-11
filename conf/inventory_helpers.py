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


def merge_inventory_video_files(
    existing_files: list[dict[str, Any]],
    current_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge video files by name while preserving first_seen_at.

    Strategy:
    - Keep all current files first (updated with preserved first_seen_at when matched).
    - Append existing files not seen in current (no deletion at this step).
    """
    existing_by_name = {item.get("name"): item for item in existing_files if item.get("name")}
    merged: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for current in current_files:
        name = current.get("name")
        current_copy = copy.deepcopy(current)
        if not name:
            merged.append(current_copy)
            continue
        seen_names.add(name)
        existing = existing_by_name.get(name)
        if existing:
            current_copy["first_seen_at"] = existing.get("first_seen_at", current_copy.get("first_seen_at"))
            current_copy["last_seen_at"] = current.get("last_seen_at", existing.get("last_seen_at"))
            current_copy["status"] = "present"
        merged.append(current_copy)

    for existing in existing_files:
        name = existing.get("name")
        if name and name in seen_names:
            continue
        merged.append(copy.deepcopy(existing))

    return merged


def merge_inventory_subfolders(
    existing_subfolders: list[dict[str, Any]],
    current_subfolders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge subfolders by name and their nested video files by name."""
    existing_by_name = {item.get("name"): item for item in existing_subfolders if item.get("name")}
    merged: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for current in current_subfolders:
        name = current.get("name")
        current_copy = copy.deepcopy(current)
        if not name:
            merged.append(current_copy)
            continue
        seen_names.add(name)
        existing = existing_by_name.get(name)
        if existing:
            current_copy["first_seen_at"] = existing.get("first_seen_at", current_copy.get("first_seen_at"))
            current_copy["last_seen_at"] = current.get("last_seen_at", existing.get("last_seen_at"))
            current_copy["status"] = "present"
            current_copy["video_files"] = merge_inventory_video_files(
                existing.get("video_files", []),
                current.get("video_files", []),
            )
        merged.append(current_copy)

    for existing in existing_subfolders:
        name = existing.get("name")
        if name and name in seen_names:
            continue
        merged.append(copy.deepcopy(existing))

    return merged


def merge_inventory_items(existing_item: dict[str, Any], current_item: dict[str, Any]) -> dict[str, Any]:
    """Merge one root inventory item by preserving historical first_seen_at."""
    merged = copy.deepcopy(current_item)
    merged["first_seen_at"] = existing_item.get("first_seen_at", current_item.get("first_seen_at"))
    merged["last_seen_at"] = current_item.get("last_seen_at", existing_item.get("last_seen_at"))
    merged["status"] = "present"
    merged["video_files"] = merge_inventory_video_files(
        existing_item.get("video_files", []),
        current_item.get("video_files", []),
    )
    if current_item.get("media_type") == "tv":
        merged["subfolders"] = merge_inventory_subfolders(
            existing_item.get("subfolders", []),
            current_item.get("subfolders", []),
        )
    return merged


def merge_inventory_documents(existing_doc: dict[str, Any], current_doc: dict[str, Any]) -> dict[str, Any]:
    """Merge existing and current inventory documents.

    - Root items matched by id.
    - Preserve existing first_seen_at when items are re-seen.
    - Keep items from existing doc not present in current scan.
    """
    existing_items = existing_doc.get("items", [])
    current_items = current_doc.get("items", [])
    existing_by_id = {item.get("id"): item for item in existing_items if item.get("id")}
    seen_ids: set[str] = set()
    merged_items: list[dict[str, Any]] = []

    for current_item in current_items:
        item_id = current_item.get("id")
        current_copy = copy.deepcopy(current_item)
        if not item_id:
            merged_items.append(current_copy)
            continue
        seen_ids.add(item_id)
        existing_item = existing_by_id.get(item_id)
        if existing_item:
            merged_items.append(merge_inventory_items(existing_item, current_item))
        else:
            merged_items.append(current_copy)

    for existing_item in existing_items:
        item_id = existing_item.get("id")
        if item_id and item_id in seen_ids:
            continue
        merged_items.append(copy.deepcopy(existing_item))

    merged_doc = copy.deepcopy(current_doc)
    merged_doc["items"] = merged_items
    return merged_doc
