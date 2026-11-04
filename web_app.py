import os
import shutil
import json
import re
import tempfile
import unicodedata
from typing import Dict, List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import pdf reader as is
from pdf_reader import run_pdf
from pdf_reader2 import (
    check_layehe,
    extract_shomare_parvande,
    classify_document,
)

from automation.electronic_contract import ElectronicContractAutomation
from automation.document_downloader import DocumentDownloaderAutomation
from automation.base import BaseAutomation
import asyncio

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# ۱. دریافت مسیر مطلق دایرکتوری که همین فایل پایتون در آن قرار دارد
BASE_DIR = Path(__file__).resolve().parent

# ۲. ترکیب مسیر پایه با نام پوشه static
STATIC_DIR = BASE_DIR / "static"


app = FastAPI(title="دستیار وکیل هوشمند API")

# Configuration file path
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


# Map of Persian labels to English keys (for internal parsing)
PERSIAN_TO_ENGLISH = {
    "شماره مشتری": "client_number",
    "شماره قرارداد": "client_number",
    "تاریخ قرارداد": "contract_date",
    "تاریخ تنظیم": "contract_date",
    "نام": "first_name",
    "نام خانوادگی": "last_name",
    "نام پدر": "fathername",
    "شماره ملی": "id_number",
    "شماره پرونده": "shomare_parvande",
    "مبلغ قرارداد": "contract_amount",
}

# Map of English keys to Persian labels (for saving)
ENGLISH_TO_PERSIAN = {
    "client_number": "شماره مشتری",
    "contract_date": "تاریخ قرارداد",
    "first_name": "نام",
    "last_name": "نام خانوادگی",
    "fathername": "نام پدر",
    "id_number": "شماره ملی",
    "shomare_parvande": "شماره پرونده",
    "contract_amount": "مبلغ قرارداد",
}


class WorkspaceConfig(BaseModel):
    workspace_path: str


class SanaCredentials(BaseModel):
    national_code: str
    password: str


class ClientCreate(BaseModel):
    first_name: str
    last_name: str
    id_number: Optional[str] = ""
    fathername: Optional[str] = ""
    client_number: Optional[str] = ""
    contract_date: Optional[str] = ""
    contract_amount: Optional[str] = ""


class ClientRename(BaseModel):
    new_name: str


class AssociatePendingRequest(BaseModel):
    filename: str
    client_folder: str
    source_folder: Optional[str] = None


class CancelAssociationRequest(BaseModel):
    filename: str
    client_folder: str


# ----------- Scan Cache helpers -----------
# The cache file lives inside the workspace directory itself,
# so it automatically follows workspace path changes.


def _scan_cache_path(workspace: str) -> str:
    return os.path.join(workspace, ".scan_cache.json")


def load_scan_cache(workspace: str) -> dict:
    """Load per-client scan cache from .scan_cache.json.
    Cache structure:
    {
      "<client_folder_name>": {
        "status": "green" | "yellow" | "red",
        "shomare_parvande": ["num1", "num2"],
        "files": { "<filename>": { "mtime": float, "is_layehe": bool } }
      },
      ...
    }
    """
    path = _scan_cache_path(workspace)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_scan_cache(workspace: str, cache: dict):
    """Persist the scan cache back to .scan_cache.json."""
    path = _scan_cache_path(workspace)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: could not save scan cache: {e}")


# ----------- Config helpers -----------
def load_config() -> str:
    """Load workspace path from config file, default to './clients' if missing"""
    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clients")
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                path = data.get("workspace_path", default_path)
                # Ensure the path exists
                os.makedirs(path, exist_ok=True)
                return path
        except Exception:
            pass

    os.makedirs(default_path, exist_ok=True)
    return default_path


def save_config(path: str):
    """Save workspace path to config file"""
    os.makedirs(path, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"workspace_path": path}, f, ensure_ascii=False, indent=4)


def normalize_persian(text: str) -> str:
    """Normalize Persian/Arabic text to canonical Unicode form.

    Fixes issues where PDF extraction produces Arabic Presentation Forms
    (U+FB50-U+FDFF, U+FE70-U+FEFF) instead of standard Arabic/Persian characters.
    Also normalizes Arabic Yeh/Kaf to Persian equivalents.
    """
    if not text:
        return text

    # NFKC normalization decomposes presentation forms to standard characters
    text = unicodedata.normalize("NFKC", text)

    # Map Arabic variants to Persian standard forms
    # Arabic Yeh (U+064A) -> Persian Yeh (U+06CC)
    text = text.replace("\u064a", "\u06cc")
    # Arabic Kaf (U+0643) -> Persian Kaf (U+06A9)
    text = text.replace("\u0643", "\u06a9")
    # Arabic Alef Maksura (U+0649) -> Persian Yeh (U+06CC)
    text = text.replace("\u0649", "\u06cc")

    # Remove zero-width characters that can cause invisible mismatches
    text = text.replace("\u200c", " ")  # Zero-width non-joiner -> space
    text = text.replace("\u200d", "")  # Zero-width joiner -> remove
    text = text.replace("\u200b", "")  # Zero-width space -> remove
    text = text.replace("\ufeff", "")  # BOM -> remove

    # Collapse multiple spaces into one
    text = re.sub(r"\s+", " ", text).strip()

    return text


def clean_folder_name(name: str) -> str:
    """Remove invalid characters from folder names and normalize Persian text"""
    name = normalize_persian(name)
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    return name.strip()


def get_client_folder_status(client_dir: str, client_name: str, cache: dict) -> tuple:
    """Determine the status of a client folder based on PDF files, using a
    per-file mtime cache to avoid re-reading unchanged PDFs.

    Returns (status, shomare_parvande_list, updated_cache_entry) where:
    - status: 'green' | 'yellow' | 'red'
    - shomare_parvande_list: list of unique شماره پرونده strings found in
      all اعلام وکالت PDFs in this folder
    - updated_cache_entry: the new cache dict entry for this client
    """
    has_layehe = False
    has_contract = False
    all_parvande = []  # collected from all اعلام وکالت PDFs

    # Load the existing cache entry for this client (or start fresh)
    entry = cache.get(client_name, {"files": {}})
    file_cache = entry.get("files", {})
    new_file_cache = {}

    if os.path.exists(client_dir) and os.path.isdir(client_dir):
        for item in os.listdir(client_dir):
            item_path = os.path.join(client_dir, item)
            if not os.path.isfile(item_path) or not item.lower().endswith(".pdf"):
                continue

            current_mtime = os.stat(item_path).st_mtime
            cached_file = file_cache.get(item)

            if cached_file and abs(cached_file.get("mtime", 0) - current_mtime) < 0.001:
                # File unchanged — use cached result
                is_layehe = cached_file.get("is_layehe", False)
                parvande_nums = cached_file.get("parvande", [])
            else:
                # File is new or modified — re-scan
                layehe_status = check_layehe(item_path)
                is_layehe = layehe_status == "it is اعلام وکالت"
                parvande_nums = extract_shomare_parvande(item_path) if is_layehe else []

            new_file_cache[item] = {
                "mtime": current_mtime,
                "is_layehe": is_layehe,
                "parvande": parvande_nums,
            }

            if is_layehe:
                has_layehe = True
                for num in parvande_nums:
                    if num not in all_parvande:
                        all_parvande.append(num)
            else:
                has_contract = True

    if has_layehe:
        status = "green"
    elif has_contract:
        status = "yellow"
    else:
        status = "red"

    new_entry = {
        "status": status,
        "shomare_parvande": all_parvande,
        "files": new_file_cache,
    }
    return status, all_parvande, new_entry


def parse_info_file(info_path: str) -> Dict[str, str]:
    """Parse key-value pairs from مشخصات موکل.txt with Farsi support"""
    meta = {}
    if not os.path.exists(info_path):
        return meta

    try:
        with open(info_path, "r", encoding="utf-8") as f:
            for line in f:
                if ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        label = normalize_persian(parts[0].strip())
                        val = normalize_persian(parts[1].strip())
                        # Map known Farsi labels to English keys, keep others as custom labels
                        english_key = PERSIAN_TO_ENGLISH.get(label, label)
                        meta[english_key] = val
    except Exception as e:
        print(f"Error parsing مشخصات موکل.txt: {e}")
    return meta


def write_info_file(info_path: str, data: dict):
    """Write metadata dict to مشخصات موکل.txt in Persian format"""
    try:
        with open(info_path, "w", encoding="utf-8") as f:
            for key, val in data.items():
                if val:
                    label = ENGLISH_TO_PERSIAN.get(key, key)
                    normalized_val = normalize_persian(str(val))
                    f.write(f"{label}: {normalized_val}\n")
    except Exception as e:
        print(f"Error writing مشخصات موکل.txt: {e}")
        raise


def merge_case_numbers_into_info(info_path: str, new_case_nums: list):
    """Merge new case numbers into a client's مشخصات موکل.txt file."""
    if not new_case_nums:
        return
    meta = parse_info_file(info_path) if os.path.exists(info_path) else {}
    existing_str = meta.get("shomare_parvande", "")
    existing_cases = [c.strip() for c in existing_str.split(",") if c.strip()]

    added = False
    for c in new_case_nums:
        if c not in existing_cases:
            existing_cases.append(c)
            added = True

    if added:
        meta["shomare_parvande"] = ", ".join(existing_cases)
        write_info_file(info_path, meta)


def find_folder_by_client_number(
    workspace_dir: str, client_number: str
) -> Optional[str]:
    """Find folder matching client number in مشخصات موکل.txt"""
    if not os.path.exists(workspace_dir):
        return None

    for item in os.listdir(workspace_dir):
        item_path = os.path.join(workspace_dir, item)
        if os.path.isdir(item_path):
            info_file = os.path.join(item_path, "مشخصات موکل.txt")
            if os.path.exists(info_file):
                meta = parse_info_file(info_file)
                if meta.get("client_number") == client_number:
                    return item_path
    return None


# API Routes
@app.get("/api/config")
async def get_config():
    path = load_config()
    return {"workspace_path": path}


@app.post("/api/config")
async def update_config(config: WorkspaceConfig):
    try:
        # Ensure workspace exists
        os.makedirs(config.workspace_path, exist_ok=True)
        save_config(config.workspace_path)
        return {"success": True, "workspace_path": config.workspace_path}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"مسیر نامعتبر است: {str(e)}")


@app.get("/api/clients")
async def list_clients():
    workspace = load_config()
    clients = []

    if not os.path.exists(workspace):
        return {"clients": []}

    # Load scan cache (avoids re-reading every PDF on every request)
    scan_cache = load_scan_cache(workspace)
    cache_dirty = False

    try:
        for item in os.listdir(workspace):
            item_path = os.path.join(workspace, item)
            if not os.path.isdir(item_path):
                continue

            info_path = os.path.join(item_path, "مشخصات موکل.txt")
            metadata = parse_info_file(info_path) if os.path.exists(info_path) else {}

            # List files inside client folder
            files = []
            for f_name in os.listdir(item_path):
                f_path = os.path.join(item_path, f_name)
                if os.path.isfile(f_path):
                    stat = os.stat(f_path)
                    files.append(
                        {
                            "name": f_name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        }
                    )

            # Use cached status/parvande where possible, rescan only changed files
            status, parvande_list, new_entry = get_client_folder_status(
                item_path, item, scan_cache
            )

            # Update cache if the entry changed
            if scan_cache.get(item) != new_entry:
                scan_cache[item] = new_entry
                cache_dirty = True

                # Auto-write شماره پرونده to مشخصات موکل.txt when it changes
                if parvande_list:
                    existing_meta = (
                        parse_info_file(info_path) if os.path.exists(info_path) else {}
                    )
                    if "shomare_parvande" not in existing_meta:
                        merged = dict(existing_meta)
                        merged["shomare_parvande"] = ", ".join(parvande_list)
                        write_info_file(info_path, merged)
                        metadata = parse_info_file(
                            info_path
                        )  # re-read to get fresh copy

            clients.append(
                {"name": item, "metadata": metadata, "files": files, "status": status}
            )

        # Persist cache if anything changed
        if cache_dirty:
            save_scan_cache(workspace, scan_cache)

        # Sort clients by name
        clients.sort(key=lambda x: x["name"])
        return {"clients": clients}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"خطا در خواندن پوشه کاری: {str(e)}"
        )


@app.post("/api/clients/create")
async def create_client(client: ClientCreate):
    workspace = load_config()
    # Normalize all input text
    normalized_data = {}
    for key, val in client.model_dump().items():
        normalized_data[key] = normalize_persian(str(val)) if val else val

    folder_name = clean_folder_name(
        f"{normalized_data['first_name']} {normalized_data['last_name']}"
    )

    if not folder_name:
        raise HTTPException(status_code=400, detail="نام و نام خانوادگی الزامی است")

    target_dir = os.path.join(workspace, folder_name)
    if os.path.exists(target_dir):
        raise HTTPException(status_code=400, detail="موکل وجود دارد")

    try:
        os.makedirs(target_dir, exist_ok=True)
        # Create عکس (photos) subfolder
        os.makedirs(os.path.join(target_dir, "عکس"), exist_ok=True)
        # Write مشخصات موکل.txt
        info_path = os.path.join(target_dir, "مشخصات موکل.txt")
        write_info_file(info_path, normalized_data)
        return {
            "success": True,
            "message": "پرونده موکل با موفقیت ایجاد شد",
            "folder_name": folder_name,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"خطا در ایجاد پرونده موکل: {str(e)}"
        )


@app.get("/api/clients/{client_name}")
async def get_client_details(client_name: str):
    workspace = load_config()
    client_dir = os.path.join(workspace, client_name)

    if not os.path.exists(client_dir) or not os.path.isdir(client_dir):
        raise HTTPException(status_code=404, detail="پوشه موکل یافت نشد")

    info_path = os.path.join(client_dir, "مشخصات موکل.txt")
    metadata = parse_info_file(info_path) if os.path.exists(info_path) else {}

    files = []
    for item in os.listdir(client_dir):
        item_path = os.path.join(client_dir, item)
        if os.path.isfile(item_path):
            stat = os.stat(item_path)
            files.append(
                {"name": item, "size": stat.st_size, "modified": stat.st_mtime}
            )

    # Gather photos from عکس subfolder
    photos = []
    photos_dir = os.path.join(client_dir, "عکس")
    if os.path.exists(photos_dir) and os.path.isdir(photos_dir):
        for item in os.listdir(photos_dir):
            item_path = os.path.join(photos_dir, item)
            if os.path.isfile(item_path) and item.lower().endswith(
                (".png", ".jpg", ".jpeg")
            ):
                stat = os.stat(item_path)
                photos.append(
                    {"name": item, "size": stat.st_size, "modified": stat.st_mtime}
                )

    # Use the scan cache for status (pass empty cache so it rescans fresh for single-client view)
    scan_cache = load_scan_cache(workspace)
    status, _, _ = get_client_folder_status(client_dir, client_name, scan_cache)
    return {
        "name": client_name,
        "metadata": metadata,
        "files": files,
        "photos": photos,
        "status": status,
    }


@app.post("/api/clients/{client_name}/save-info")
async def save_client_info(client_name: str, metadata: dict):
    workspace = load_config()
    client_dir = os.path.join(workspace, client_name)

    if not os.path.exists(client_dir) or not os.path.isdir(client_dir):
        raise HTTPException(status_code=404, detail="پوشه موکل یافت نشد")

    try:
        info_path = os.path.join(client_dir, "مشخصات موکل.txt")
        write_info_file(info_path, metadata)
        return {"success": True, "message": "اطلاعات موکل با موفقیت ذخیره شد"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"خطا در ذخیره‌سازی اطلاعات: {str(e)}"
        )


def update_client_from_files_impl(client_name: str, workspace: str) -> dict:
    client_dir = os.path.join(workspace, client_name)
    if not os.path.exists(client_dir) or not os.path.isdir(client_dir):
        return {"success": False, "message": "پوشه موکل یافت نشد"}

    info_path = os.path.join(client_dir, "مشخصات موکل.txt")
    meta = parse_info_file(info_path) if os.path.exists(info_path) else {}

    updated = False
    all_case_nums = set(
        [c.strip() for c in meta.get("shomare_parvande", "").split(",") if c.strip()]
    )

    from pdf_reader import run_pdf
    from pdf_reader2 import extract_info, extract_shomare_parvande

    for item in os.listdir(client_dir):
        item_path = os.path.join(client_dir, item)
        if os.path.isfile(item_path) and item.lower().endswith(".pdf"):
            text = extract_info(item_path)
            doc_type = classify_document(text)

            if doc_type == "CONTRACT":
                extracted = run_pdf(item_path)
                if extracted:
                    for k, v in extracted.items():
                        if meta.get(k) != v and v:
                            meta[k] = v
                            updated = True

            if doc_type in ["LAYEHE", "CONTRACT"]:
                case_nums = extract_shomare_parvande(item_path)
                for c in case_nums:
                    if c not in all_case_nums:
                        all_case_nums.add(c)
                        updated = True

    if all_case_nums:
        new_parvande = ", ".join(sorted(list(all_case_nums)))
        if meta.get("shomare_parvande") != new_parvande:
            meta["shomare_parvande"] = new_parvande
            updated = True

    if updated or not os.path.exists(info_path):
        write_info_file(info_path, meta)
        scan_cache = load_scan_cache(workspace)
        if client_name in scan_cache:
            del scan_cache[client_name]
            save_scan_cache(workspace, scan_cache)

    return {
        "success": True,
        "message": "اطلاعات موکل به‌روزرسانی شد",
        "updated": updated,
    }


@app.post("/api/clients/{client_name}/update-from-files")
async def update_client_from_files(client_name: str):
    workspace = load_config()
    result = update_client_from_files_impl(client_name, workspace)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/api/clients/update-all-from-files")
async def update_all_clients_from_files():
    workspace = load_config()
    if not os.path.exists(workspace):
        return {"success": True, "updated_count": 0}

    updated_count = 0
    for item in os.listdir(workspace):
        item_path = os.path.join(workspace, item)
        if os.path.isdir(item_path):
            res = update_client_from_files_impl(item, workspace)
            if res.get("updated"):
                updated_count += 1

    return {
        "success": True,
        "message": f"اطلاعات {updated_count} موکل بروزرسانی شد",
        "updated_count": updated_count,
    }


@app.post("/api/clients/{client_name}/rename")
async def rename_client(client_name: str, body: ClientRename):
    workspace = load_config()
    src_dir = os.path.join(workspace, client_name)
    new_folder_name = clean_folder_name(body.new_name)
    dst_dir = os.path.join(workspace, new_folder_name)

    if not os.path.exists(src_dir) or not os.path.isdir(src_dir):
        raise HTTPException(status_code=404, detail="پوشه موکل یافت نشد")

    if not new_folder_name:
        raise HTTPException(status_code=400, detail="نام پوشه جدید نامعتبر است")

    if os.path.exists(dst_dir) and src_dir != dst_dir:
        raise HTTPException(
            status_code=400, detail="پوشه‌ای با این نام در سیستم وجود دارد"
        )

    try:
        shutil.move(src_dir, dst_dir)
        return {"success": True, "new_name": new_folder_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در تغییر نام پوشه: {str(e)}")


@app.delete("/api/clients/{client_name}")
async def delete_client(client_name: str):
    workspace = load_config()
    client_dir = os.path.join(workspace, client_name)

    if not os.path.exists(client_dir) or not os.path.isdir(client_dir):
        raise HTTPException(status_code=404, detail="پوشه موکل یافت نشد")

    try:
        shutil.rmtree(client_dir)
        return {
            "success": True,
            "message": "پرونده موکل به همراه فایل‌ها به طور کامل حذف شد",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در حذف پرونده: {str(e)}")


@app.post("/api/clients/{client_name}/upload")
async def upload_to_client(client_name: str, files: List[UploadFile] = File(...)):
    workspace = load_config()
    client_dir = os.path.join(workspace, client_name)

    if not os.path.exists(client_dir) or not os.path.isdir(client_dir):
        raise HTTPException(status_code=404, detail="پوشه موکل یافت نشد")

    uploaded_files = []
    try:
        for file in files:
            target_path = os.path.join(client_dir, file.filename)
            with open(target_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_files.append(file.filename)

        # Invalidate cache entry so the next /api/clients call re-scans this client
        scan_cache = load_scan_cache(workspace)
        if client_name in scan_cache:
            del scan_cache[client_name]
            save_scan_cache(workspace, scan_cache)

        return {"success": True, "uploaded": uploaded_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در بارگذاری فایل‌ها: {str(e)}")


@app.get("/api/clients/{client_name}/files/{filename}")
async def get_client_file(
    client_name: str, filename: str, download: bool = Query(False)
):
    workspace = load_config()
    file_path = os.path.join(workspace, client_name, filename)

    if not os.path.exists(file_path) or os.path.isdir(file_path):
        raise HTTPException(status_code=404, detail="فایل یافت نشد")

    # Serve files to view or trigger direct download
    headers = {}
    if download:
        import urllib.parse

        encoded_filename = urllib.parse.quote(filename)
        headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{encoded_filename}"
        )

    return FileResponse(file_path, headers=headers)


@app.delete("/api/clients/{client_name}/files/{filename}")
async def delete_client_file(client_name: str, filename: str):
    workspace = load_config()
    file_path = os.path.join(workspace, client_name, filename)

    if not os.path.exists(file_path) or os.path.isdir(file_path):
        raise HTTPException(status_code=404, detail="فایل یافت نشد")

    try:
        os.remove(file_path)

        # Invalidate cache entry so the next /api/clients call re-scans this client
        scan_cache = load_scan_cache(workspace)
        if client_name in scan_cache:
            del scan_cache[client_name]
            save_scan_cache(workspace, scan_cache)

        return {"success": True, "message": "فایل با موفقیت حذف شد"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در حذف فایل: {str(e)}")


# Photo endpoints
@app.post("/api/clients/{client_name}/upload-photo")
async def upload_photo(client_name: str, files: List[UploadFile] = File(...)):
    workspace = load_config()
    client_dir = os.path.join(workspace, client_name)

    if not os.path.exists(client_dir) or not os.path.isdir(client_dir):
        raise HTTPException(status_code=404, detail="پوشه موکل یافت نشد")

    photos_dir = os.path.join(client_dir, "عکس")
    os.makedirs(photos_dir, exist_ok=True)

    uploaded = []
    for file in files:
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ("png", "jpg", "jpeg"):
            continue  # Skip non-image files
        target_path = os.path.join(photos_dir, file.filename)
        try:
            with open(target_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded.append(file.filename)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"خطا در بارگذاری عکس: {str(e)}"
            )

    if not uploaded:
        raise HTTPException(
            status_code=400, detail="لطفاً فقط فایل‌های PNG یا JPG انتخاب کنید"
        )

    return {"success": True, "uploaded": uploaded}


@app.get("/api/clients/{client_name}/photos")
async def list_photos(client_name: str):
    workspace = load_config()
    photos_dir = os.path.join(workspace, client_name, "عکس")

    if not os.path.exists(photos_dir):
        return {"photos": []}

    photos = []
    for item in os.listdir(photos_dir):
        item_path = os.path.join(photos_dir, item)
        if os.path.isfile(item_path) and item.lower().endswith(
            (".png", ".jpg", ".jpeg")
        ):
            stat = os.stat(item_path)
            photos.append(
                {"name": item, "size": stat.st_size, "modified": stat.st_mtime}
            )
    return {"photos": photos}


@app.get("/api/clients/{client_name}/photos/{filename}")
async def get_photo(client_name: str, filename: str):
    workspace = load_config()
    file_path = os.path.join(workspace, client_name, "عکس", filename)

    if not os.path.exists(file_path) or os.path.isdir(file_path):
        raise HTTPException(status_code=404, detail="عکس یافت نشد")

    return FileResponse(file_path)


@app.delete("/api/clients/{client_name}/photos/{filename}")
async def delete_photo(client_name: str, filename: str):
    workspace = load_config()
    file_path = os.path.join(workspace, client_name, "عکس", filename)

    if not os.path.exists(file_path) or os.path.isdir(file_path):
        raise HTTPException(status_code=404, detail="عکس یافت نشد")

    try:
        os.remove(file_path)
        return {"success": True, "message": "عکس با موفقیت حذف شد"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در حذف عکس: {str(e)}")


@app.post("/api/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    workspace = load_config()

    if not file.filename.lower().endswith(".pdf"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "خطا: لطفاً یک فایل PDF انتخاب کنید"},
        )

    # Save file to a temporary location to run the PDF reader
    temp_dir = tempfile.gettempdir()
    temp_pdf_path = os.path.join(temp_dir, f"temp_{file.filename}")

    try:
        with open(temp_pdf_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Call the existing extraction logic
        extracted_data = run_pdf(temp_pdf_path)

        # Extract full text for classification and client number matching
        from pdf_reader2 import extract_info, classify_document, extract_client_number

        full_text = extract_info(temp_pdf_path)
        doc_type = classify_document(full_text)

        # Extract client contract number and case numbers
        client_num = extract_client_number(full_text)
        case_nums = extract_shomare_parvande(temp_pdf_path)

        # Use system temp directory for pending uploads to avoid cluttering workspace
        pending_dir = os.path.join(tempfile.gettempdir(), "lawyer_assistant_pending")
        os.makedirs(pending_dir, exist_ok=True)

        # Define a helper function to save to pending dir when matching fails
        def save_to_pending():
            target_path = os.path.join(pending_dir, file.filename)
            shutil.copy2(temp_pdf_path, target_path)
            return {
                "success": True,
                "matched": False,
                "filename": file.filename,
                "document_type": doc_type,
                "message": f"سند غیرمرتبط با نوع '{doc_type}' شناسایی شد و به پوشه اسناد در انتظار انتقال یافت.",
            }

        # Helper to find client matching any extracted case number in their مشخصات موکل.txt
        def find_client_by_case_number(case_numbers):
            if not os.path.exists(workspace):
                return None
            for item in os.listdir(workspace):
                item_path = os.path.join(workspace, item)
                if os.path.isdir(item_path):
                    info_file = os.path.join(item_path, "مشخصات موکل.txt")
                    if os.path.exists(info_file):
                        meta = parse_info_file(info_file)
                        parvande_str = meta.get("shomare_parvande", "")
                        client_cases = [
                            c.strip() for c in parvande_str.split(",") if c.strip()
                        ]
                        if any(c in client_cases for c in case_numbers):
                            return item
            return None

        # Check matching rules:
        if case_nums:
            # Rule 2: If we see a case number, check if it matches an existing client's مشخصات موکل.txt
            matched_client = find_client_by_case_number(case_nums)
            if matched_client:
                target_folder = os.path.join(workspace, matched_client)
                target_pdf_path = os.path.join(target_folder, file.filename)
                shutil.copy2(temp_pdf_path, target_pdf_path)

                # Merge case numbers so we don't lose track of new ones in the document
                info_path = os.path.join(target_folder, "مشخصات موکل.txt")
                merge_case_numbers_into_info(info_path, case_nums)

                # Invalidate cache
                scan_cache = load_scan_cache(workspace)
                if matched_client in scan_cache:
                    del scan_cache[matched_client]
                    save_scan_cache(workspace, scan_cache)
                return {
                    "success": True,
                    "matched": True,
                    "auto_matched_by_case": True,
                    "folder_name": matched_client,
                    "filename": file.filename,
                    "message": f"سند با موفقیت به صورت خودکار به پرونده '{matched_client}' اضافه شد.",
                }
            else:
                # Unknown/New case number -> ask which user this is for
                return save_to_pending()
        else:
            # Rule 1: If it has contract number and doesn't have case numbers -> do normal matching
            if doc_type == "CONTRACT":
                if not extracted_data:
                    return save_to_pending()

                ghrardad_zamime = extracted_data.get("ghrardad_zamime")
                first_name = extracted_data.get("first_name")
                last_name = extracted_data.get("last_name")

                # Scenario 1: Accessory contract file
                if ghrardad_zamime and (not first_name or not last_name):
                    target_folder = find_folder_by_client_number(
                        workspace, ghrardad_zamime
                    )
                    if target_folder:
                        target_pdf_path = os.path.join(target_folder, file.filename)
                        shutil.copy2(temp_pdf_path, target_pdf_path)
                        folder_name = os.path.basename(target_folder)
                        # Invalidate cache
                        scan_cache = load_scan_cache(workspace)
                        if folder_name in scan_cache:
                            del scan_cache[folder_name]
                            save_scan_cache(workspace, scan_cache)
                        return {
                            "success": True,
                            "matched": True,
                            "message": f"موفق! فایل به پوشه موکل موجود اضافه شد: {folder_name}",
                            "folder_name": folder_name,
                        }
                    else:
                        return save_to_pending()

                # Scenario 2: Main contract file
                if not first_name or not last_name:
                    return save_to_pending()

                base_folder_name = clean_folder_name(f"{first_name} {last_name}")
                folder_name = base_folder_name
                target_folder = os.path.join(workspace, folder_name)

                # Handling multiple contracts for the same client
                counter = 2
                while os.path.exists(target_folder) and os.path.isdir(target_folder):
                    # Check if the exact same contract exists in this folder
                    info_file = os.path.join(target_folder, "مشخصات موکل.txt")
                    if os.path.exists(info_file):
                        meta = parse_info_file(info_file)
                        existing_client_num = meta.get("client_number")
                        if (
                            existing_client_num
                            and client_num
                            and existing_client_num == client_num
                        ):
                            break  # Same contract, just use this folder

                    folder_name = f"{base_folder_name} {counter}"
                    target_folder = os.path.join(workspace, folder_name)
                    counter += 1

                pdf_name_to_save = (
                    f"قرارداد الکترونیک وکالت {first_name} {last_name}.pdf"
                )

                if os.path.exists(target_folder) and os.path.isdir(target_folder):
                    target_pdf_path = os.path.join(target_folder, pdf_name_to_save)
                    shutil.copy2(temp_pdf_path, target_pdf_path)
                    # Invalidate cache
                    scan_cache = load_scan_cache(workspace)
                    if folder_name in scan_cache:
                        del scan_cache[folder_name]
                        save_scan_cache(workspace, scan_cache)
                    return {
                        "success": True,
                        "matched": True,
                        "message": "موکل وجود دارد. فایل به پوشه موکل اضافه شد.",
                        "folder_name": folder_name,
                    }

                # Create folder and save
                os.makedirs(target_folder, exist_ok=True)
                os.makedirs(os.path.join(target_folder, "عکس"), exist_ok=True)
                target_pdf_path = os.path.join(target_folder, pdf_name_to_save)
                shutil.copy2(temp_pdf_path, target_pdf_path)

                # Generate مشخصات موکل.txt file
                info_file_path = os.path.join(target_folder, "مشخصات موکل.txt")
                normalized_extracted = {}
                for k, v in extracted_data.items():
                    normalized_extracted[k] = normalize_persian(str(v)) if v else v
                write_info_file(info_file_path, normalized_extracted)

                # Invalidate cache
                scan_cache = load_scan_cache(workspace)
                if folder_name in scan_cache:
                    del scan_cache[folder_name]
                    save_scan_cache(workspace, scan_cache)

                return {
                    "success": True,
                    "matched": True,
                    "message": f"موفق! پرونده ایجاد شد: {folder_name}",
                    "folder_name": folder_name,
                }

            elif doc_type == "DADKHAST" or doc_type == "LAYEHE":
                if client_num:
                    target_folder = find_folder_by_client_number(workspace, client_num)
                    if target_folder:
                        target_pdf_path = os.path.join(target_folder, file.filename)
                        shutil.copy2(temp_pdf_path, target_pdf_path)
                        folder_name = os.path.basename(target_folder)
                        # Invalidate cache
                        scan_cache = load_scan_cache(workspace)
                        if folder_name in scan_cache:
                            del scan_cache[folder_name]
                            save_scan_cache(workspace, scan_cache)
                        return {
                            "success": True,
                            "matched": True,
                            "message": f"موفق! سند به پوشه موکل مرتبط اضافه شد: {folder_name}",
                            "folder_name": folder_name,
                        }
                return save_to_pending()
            else:
                return save_to_pending()

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"خطا در پردازش فایل: {str(e)}"},
        )
    finally:
        # Cleanup temp file
        if os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass


@app.post("/api/associate-pending")
async def associate_pending(body: AssociatePendingRequest):
    workspace = load_config()

    # Resolve source path
    if body.source_folder and body.source_folder != ".pending_uploads":
        source_path = os.path.join(workspace, body.source_folder, body.filename)
    else:
        import tempfile

        source_path = os.path.join(
            tempfile.gettempdir(), "lawyer_assistant_pending", body.filename
        )

    dest_folder = os.path.join(workspace, body.client_folder)

    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="فایل مبدأ یافت نشد")

    if not os.path.exists(dest_folder) or not os.path.isdir(dest_folder):
        raise HTTPException(status_code=404, detail="پوشه موکل مورد نظر یافت نشد")

    try:
        dest_path = os.path.join(dest_folder, body.filename)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        shutil.move(source_path, dest_path)

        # If it's a PDF, try to extract case numbers and merge them so future matches work automatically
        if dest_path.lower().endswith(".pdf"):
            from pdf_reader2 import extract_shomare_parvande

            case_nums = extract_shomare_parvande(dest_path)
            if case_nums:
                info_path = os.path.join(dest_folder, "مشخصات موکل.txt")
                merge_case_numbers_into_info(info_path, case_nums)

        # Invalidate cache for both client folders
        scan_cache = load_scan_cache(workspace)
        cache_dirty = False

        if body.client_folder in scan_cache:
            del scan_cache[body.client_folder]
            cache_dirty = True

        if body.source_folder and body.source_folder in scan_cache:
            del scan_cache[body.source_folder]
            cache_dirty = True

        if cache_dirty:
            save_scan_cache(workspace, scan_cache)

        return {
            "success": True,
            "message": f"سند با موفقیت به پرونده '{body.client_folder}' متصل شد",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در اتصال سند: {str(e)}")


@app.post("/api/cancel-association")
async def cancel_association(body: CancelAssociationRequest):
    workspace = load_config()
    file_path = os.path.join(workspace, body.client_folder, body.filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="فایل یافت نشد")

    try:
        os.remove(file_path)

        # Invalidate cache for client
        scan_cache = load_scan_cache(workspace)
        if body.client_folder in scan_cache:
            del scan_cache[body.client_folder]
            save_scan_cache(workspace, scan_cache)

        return {"success": True, "message": "عملیات لغو شد و فایل حذف گردید"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در لغو عملیات: {str(e)}")


@app.post("/api/automation/auto-contract")
async def trigger_auto_contract():
    try:
        automation = ElectronicContractAutomation()
        result = await automation.run_auto_download_contracts()
        if result.get("success"):
            return result
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get("message", "خطای ناشناخته در اتوماسیون"),
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در اجرای اتوماسیون: {str(e)}")


@app.get("/api/automation/settings")
def get_sana_settings():
    try:
        project_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(project_dir, "sana_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "national_code": data.get("national_code", ""),
                    "password": data.get("password", ""),
                }
        return {"national_code": "", "password": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در خواندن تنظیمات: {str(e)}")


@app.post("/api/automation/settings")
def save_sana_settings(creds: SanaCredentials):
    try:
        project_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(project_dir, "sana_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {"national_code": creds.national_code, "password": creds.password},
                f,
                ensure_ascii=False,
            )
        return {"success": True, "message": "تنظیمات با موفقیت ذخیره شد"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در ذخیره تنظیمات: {str(e)}")


@app.post("/api/automation/cancel")
def cancel_automation():
    try:
        success = BaseAutomation.cancel_current()
        if success:
            return {"success": True, "message": "درخواست توقف ارسال شد"}
        else:
            return {"success": False, "message": "اتوماسیونی در حال اجرا نیست"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در توقف اتوماسیون: {str(e)}")


class SetClientRequest(BaseModel):
    client_id: str


# Global instance for interactive automation
document_downloader_instance = None

class DocumentDownloaderRequest(BaseModel):
    client_id: str
    national_id: str
    contract_date: str

@app.post("/api/automation/document-downloader/start")
async def start_document_downloader(req: DocumentDownloaderRequest):
    global document_downloader_instance
    try:
        workspace_path = load_config()
        if not workspace_path or not os.path.exists(workspace_path):
            return {"success": False, "message": "پوشه کاری یافت نشد"}

        client_dir = os.path.join(workspace_path, req.client_id)
        if not os.path.exists(client_dir):
            return {"success": False, "message": "پوشه موکل یافت نشد"}

        if not req.national_id or not req.contract_date:
            return {"success": False, "message": "کد ملی و تاریخ قرارداد الزامی است"}

        document_downloader_instance = DocumentDownloaderAutomation()

        asyncio.create_task(
            document_downloader_instance.run_downloader(workspace_path, client_dir, req.national_id, req.contract_date)
        )

        return {"success": True, "message": "دانلود لوایح موکل آغاز شد"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در شروع اتوماسیون: {str(e)}")

@app.get("/api/automation/document-downloader/status")
async def status_document_downloader():
    global document_downloader_instance
    if not document_downloader_instance:
        return {"status": "NONE"}

    return {
        "status": document_downloader_instance.status,
        "message": document_downloader_instance.status_message,
    }


# Mount static files SPA
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
