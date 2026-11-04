"""
One-time migration script to normalize existing client folder names.
Renames folders with Arabic Presentation Form characters to standard Persian Unicode.
Also creates missing عکس (photos) subfolders.

Run this once: python migrate_folders.py
"""

import os
import sys
import unicodedata
import re

# Fix Windows console encoding for Persian output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def normalize_persian(text: str) -> str:
    """Normalize Persian/Arabic text to canonical Unicode form."""
    if not text:
        return text

    text = unicodedata.normalize("NFKC", text)

    # Arabic Yeh -> Persian Yeh
    text = text.replace("\u064a", "\u06cc")
    # Arabic Kaf -> Persian Kaf
    text = text.replace("\u0643", "\u06a9")
    # Arabic Alef Maksura -> Persian Yeh
    text = text.replace("\u0649", "\u06cc")

    # Remove zero-width characters
    text = text.replace("\u200c", " ")
    text = text.replace("\u200d", "")
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


def clean_folder_name(name: str) -> str:
    name = normalize_persian(name)
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    return name.strip()


def migrate(workspace_path: str):
    if not os.path.exists(workspace_path):
        print(f"[!] Path does not exist: {workspace_path}")
        return

    print(f"[*] Migrating folders in: {workspace_path}")
    print("=" * 60)

    renamed_count = 0
    photos_created_count = 0
    skipped_conflicts = []

    # Get all directories first (avoid modifying while iterating)
    entries = []
    for item in os.listdir(workspace_path):
        item_path = os.path.join(workspace_path, item)
        if os.path.isdir(item_path):
            entries.append((item, item_path))

    for folder_name, folder_path in entries:
        normalized = clean_folder_name(folder_name)

        # Create عکس subfolder if missing
        photos_dir = os.path.join(folder_path, "عکس")
        if not os.path.exists(photos_dir):
            os.makedirs(photos_dir, exist_ok=True)
            photos_created_count += 1

        # Check if rename is needed
        if normalized != folder_name:
            new_path = os.path.join(workspace_path, normalized)

            if os.path.exists(new_path) and new_path != folder_path:
                # Conflict: target already exists
                skipped_conflicts.append((folder_name, normalized))
                print(
                    f"  [CONFLICT] '{folder_name}' -> '{normalized}' (target already exists, skipping)"
                )
                continue

            try:
                os.rename(folder_path, new_path)
                renamed_count += 1
                print(f"  [RENAMED] '{folder_name}' -> '{normalized}'")

                # Update عکس folder reference after rename
                photos_dir_new = os.path.join(new_path, "عکس")
                if not os.path.exists(photos_dir_new):
                    os.makedirs(photos_dir_new, exist_ok=True)
            except Exception as e:
                print(f"  [ERROR] Failed to rename '{folder_name}': {e}")
        else:
            print(f"  [OK] '{folder_name}' (already normalized)")

    print("\n" + "=" * 60)
    print("[*] Migration complete!")
    print(f"    Folders renamed: {renamed_count}")
    print(f"    Photos subfolders created: {photos_created_count}")
    if skipped_conflicts:
        print(f"    Skipped (conflicts): {len(skipped_conflicts)}")
        for old, new in skipped_conflicts:
            print(f"      '{old}' -> '{new}'")


if __name__ == "__main__":
    # Load workspace from config.json or use default
    config_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"
    )
    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clients")

    workspace = default_path
    if os.path.exists(config_file):
        import json

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                workspace = data.get("workspace_path", default_path)
        except Exception:
            pass

    print(f"\nThis script will normalize Persian folder names in: {workspace}")
    print("It will also create missing 'عکس' (photos) subfolders.\n")

    confirm = input("Continue? (y/n): ").strip().lower()
    if confirm in ("y", "yes"):
        migrate(workspace)
    else:
        print("Aborted.")
