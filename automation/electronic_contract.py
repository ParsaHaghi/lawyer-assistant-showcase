import os
import time
import asyncio
from automation.base import BaseAutomation


class ElectronicContractAutomation(BaseAutomation):
    async def run_auto_download_contracts(self):
        """
        Automates the process of logging into Adliran, navigating to contracts,
        downloading them, and creating client folders.
        """
        from web_app import load_config

        workspace = load_config()
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # Get the actual root of the project to find the config or we can store it in the current dir
        project_dir = os.path.dirname(base_dir)

        try:
            await self.setup_browser(headless=False)

            login_success = await self.login_to_sana(project_dir)
            if not login_success:
                await self.teardown_browser()
                return {
                    "success": False,
                    "message": "زمان انتظار برای ورود به سیستم پایان یافت. لطفاً دوباره تلاش کنید.",
                }

            self.check_cancelled()

            # Click on "قراردادهای الکترونیک من" (My Electronic Contracts)
            try:
                sidebar_item = (
                    self.page.locator("a", has_text="قراردادهاي الكترونيك من")
                    .filter(visible=True)
                    .first
                )
                if await sidebar_item.count() > 0:
                    await sidebar_item.click(force=True)
                else:
                    await self.page.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const target = links.find(a => a.innerText.includes('قراردادهاي الكترونيك من') || a.innerText.includes('قراردادهای الکترونیک من'));
                        if (target) target.click();
                    }""")
                await self.page.wait_for_timeout(3000)
            except Exception as e:
                print(f"[Automation] Error clicking 'My Electronic Contracts': {e}")
                await self.teardown_browser()
                return {
                    "success": False,
                    "message": "خطا در یافتن منوی 'قراردادهای الکترونیک من'",
                }

            self.check_cancelled()

            # Click on "قراردادهایی که من وکیل آن می باشم" checkbox
            try:
                await self.page.wait_for_selector(
                    "text=قراردادهایی که من وکیل آن می باشم", timeout=10000
                )
                await self.page.locator(
                    "text=قراردادهایی که من وکیل آن می باشم"
                ).click()
                await self.page.wait_for_timeout(1000)
            except Exception as e:
                print(f"[Automation] Error checking 'Contracts I am lawyer of': {e}")
                pass

            self.check_cancelled()

            # Click on "بازیابی قرارداد وکالت با شرایط فوق" button
            try:
                retrieve_btn = (
                    self.page.locator("button, a").filter(has_text="بازیابی").first
                )
                await retrieve_btn.click(force=True)

                await self.page.wait_for_selector(
                    "button:has-text('نمایش قرارداد'), a:has-text('نمایش قرارداد')",
                    timeout=15000,
                )
                await self.page.wait_for_timeout(2000)
            except Exception:
                try:
                    await self.page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button, a'));
                        const target = btns.find(b => b.innerText.includes('بازیابی'));
                        if (target) target.click();
                    }""")
                    await self.page.wait_for_selector(
                        "button:has-text('نمایش قرارداد'), a:has-text('نمایش قرارداد')",
                        timeout=15000,
                    )
                    await self.page.wait_for_timeout(2000)
                except Exception as e2:
                    print(
                        f"[Automation] Error clicking retrieve button or no results found: {e2}"
                    )
                    await self.teardown_browser()
                    return {
                        "success": False,
                        "message": "قراردادی یافت نشد یا خطا در بازیابی اطلاعات",
                    }

            self.check_cancelled()

            processed_count = 0
            has_next_page = True

            # Build a cache of existing contracts
            existing_contracts = set()
            for item in os.listdir(workspace):
                item_path = os.path.join(workspace, item)
                if os.path.isdir(item_path):
                    info_file = os.path.join(item_path, "مشخصات موکل.txt")
                    if os.path.exists(info_file):
                        try:
                            with open(info_file, "r", encoding="utf-8") as f:
                                content = f.read()
                                import re

                                matches = re.findall(r"14\d{12,14}", content)
                                for match in matches:
                                    existing_contracts.add(match)
                        except Exception:
                            pass

            processed_file_global = os.path.join(workspace, "processed_contracts.txt")
            try:
                with open(processed_file_global, "w", encoding="utf-8") as f:
                    for c in existing_contracts:
                        f.write(f"{c}\n")
            except Exception:
                pass

            while has_next_page:
                self.check_cancelled()
                contract_buttons = await self.page.locator(
                    "button:has-text('نمایش قرارداد')"
                ).all()

                for i in range(len(contract_buttons)):
                    self.check_cancelled()
                    buttons = await self.page.locator(
                        "button:has-text('نمایش قرارداد')"
                    ).all()
                    if i >= len(buttons):
                        break

                    button = buttons[i]

                    try:
                        row = button.locator("xpath=ancestor::tr")
                        row_text = await row.inner_text()
                        import re

                        if "تاييد شده" not in row_text:
                            print(
                                "[Automation] Skipping contract because status is not 'تایید شده'"
                            )
                            continue

                        if re.search(r"تاييد شده\s+(?:1|۱)(?:\s|$)", row_text):
                            print("[Automation] Skipping contract with fee 1")
                            continue

                        match = re.search(r"14\d{12,14}", row_text)
                        contract_num = match.group(0) if match else None
                    except Exception:
                        contract_num = None

                    if contract_num and contract_num in existing_contracts:
                        print(
                            f"[Automation] Skipping already processed contract: {contract_num}"
                        )
                        continue

                    print(
                        f"[Automation] Clicking contract {contract_num or (i + 1)}..."
                    )

                    try:
                        await button.click(timeout=5000)
                        await self.page.wait_for_selector(
                            "text='چاپ پیش نویس قرارداد'", timeout=60000
                        )
                    except Exception as click_err:
                        print(
                            f"[Automation] Click error or detail view not loaded: {click_err}"
                        )
                        print(
                            "[Automation] The site took more than 1 minute to load. Ending task early."
                        )
                        has_next_page = False
                        break

                    self.check_cancelled()
                    print(
                        "[Automation] Detail view loaded. Clicking 'چاپ پیش نویس قرارداد' ..."
                    )

                    page_promise = asyncio.create_task(
                        self.context.wait_for_event("page")
                    )
                    download_promise = asyncio.create_task(
                        self.page.wait_for_event("download")
                    )

                    try:
                        print_btn = self.page.locator(
                            "text='چاپ پیش نویس قرارداد'"
                        ).first
                        await print_btn.click(timeout=5000)
                    except Exception as e:
                        print(
                            f"[Automation] Could not click 'چاپ پیش نویس قرارداد': {e}"
                        )

                    done, pending = await asyncio.wait(
                        [page_promise, download_promise],
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=60.0,
                    )

                    for p in pending:
                        p.cancel()

                    self.check_cancelled()
                    import tempfile
                    import uuid

                    downloads_dir = tempfile.gettempdir()

                    old_pending_dir = os.path.join(workspace, "pending_uploads")
                    if os.path.exists(old_pending_dir):
                        import shutil

                        try:
                            shutil.rmtree(old_pending_dir)
                        except Exception:
                            pass

                    if download_promise in done and not download_promise.exception():
                        download = download_promise.result()
                        file_path = os.path.join(
                            downloads_dir, f"contract_{uuid.uuid4().hex[:8]}.pdf"
                        )
                        await download.save_as(file_path)
                        print(f"[Automation] Downloaded direct file: {file_path}")
                        await process_downloaded_pdf(file_path, workspace)
                        processed_count += 1
                        if contract_num:
                            existing_contracts.add(contract_num)
                            processed_file = os.path.join(
                                workspace, "processed_contracts.txt"
                            )
                            with open(processed_file, "a", encoding="utf-8") as f:
                                f.write(f"{contract_num}\n")

                    elif page_promise in done and not page_promise.exception():
                        new_page = page_promise.result()
                        try:
                            await new_page.wait_for_load_state(
                                "networkidle", timeout=15000
                            )
                        except Exception:
                            pass
                        print(f"[Automation] New page opened: {new_page.url}")

                        try:
                            await new_page.evaluate("window.print = () => {}")
                        except Exception:
                            pass

                        try:
                            await new_page.evaluate("""() => {
                                const elements = document.querySelectorAll('button, a, input, .print-btn, [class*="print"]');
                                for(let el of elements) {
                                    if(el.innerText && (el.innerText.includes('چاپ') || el.innerText.includes('Print'))) {
                                        el.style.display = 'none';
                                    }
                                }
                            }""")
                        except Exception:
                            pass

                        file_path = os.path.join(
                            downloads_dir, f"contract_{uuid.uuid4().hex[:8]}.pdf"
                        )

                        try:
                            client = await new_page.context.new_cdp_session(new_page)
                            result = await client.send(
                                "Page.printToPDF",
                                {
                                    "landscape": False,
                                    "displayHeaderFooter": False,
                                    "printBackground": True,
                                    "preferCSSPageSize": True,
                                },
                            )
                            import base64

                            pdf_data = base64.b64decode(result["data"])
                            with open(file_path, "wb") as f:
                                f.write(pdf_data)

                            print(f"[Automation] Generated PDF via CDP to: {file_path}")
                            await process_downloaded_pdf(file_path, workspace)
                            processed_count += 1
                            if contract_num:
                                existing_contracts.add(contract_num)
                                processed_file = os.path.join(
                                    workspace, "processed_contracts.txt"
                                )
                                with open(processed_file, "a", encoding="utf-8") as f:
                                    f.write(f"{contract_num}\n")
                        except Exception as cdp_err:
                            print(f"[Automation] CDP printToPDF failed: {cdp_err}")

                        await new_page.close()
                    else:
                        print("[Automation] No new popup or download detected.")
                        try:
                            close_btn = (
                                self.page.locator("button, a")
                                .filter(has_text="بستن")
                                .first
                            )
                            if await close_btn.count() > 0:
                                await close_btn.click(force=True)
                            else:
                                await self.page.locator("button.close").first.click(
                                    force=True, timeout=2000
                                )
                        except Exception:
                            pass

                    self.check_cancelled()
                    print("[Automation] Returning to contracts list...")
                    try:
                        sidebar_item = (
                            self.page.locator("a", has_text="قراردادهاي الكترونيك من")
                            .filter(visible=True)
                            .first
                        )
                        if await sidebar_item.count() > 0:
                            await sidebar_item.click(force=True)
                        else:
                            await self.page.evaluate("""() => {
                                const links = Array.from(document.querySelectorAll('a'));
                                const target = links.find(a => a.innerText.includes('قراردادهاي الكترونيك من') || a.innerText.includes('قراردادهای الکترونیک من'));
                                if (target) target.click();
                            }""")

                        await self.page.wait_for_selector(
                            "button:has-text('نمایش قرارداد'), a:has-text('نمایش قرارداد')",
                            timeout=60000,
                        )
                        await self.page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"[Automation] Error returning to list: {e}")
                        print(
                            "[Automation] The site took more than 1 minute to load. Ending task early."
                        )
                        has_next_page = False
                        break

                    await self.page.wait_for_timeout(1000)

                self.check_cancelled()
                try:
                    next_btn = self.page.locator("text=بعدی").first
                    if await next_btn.count() > 0 and await next_btn.is_enabled():
                        await next_btn.click()
                        await self.page.wait_for_timeout(3000)
                    else:
                        has_next_page = False
                except Exception:
                    has_next_page = False

            await self.teardown_browser()

            print(
                "[Automation] Scanning for manually downloaded contracts in Desktop and Downloads..."
            )
            found_manual_files = await scan_and_import_manual_downloads(workspace)
            if found_manual_files > 0:
                return {
                    "success": True,
                    "message": f"عملیات با موفقیت پایان یافت. تعداد {processed_count} قرارداد اتوماتیک دریافت شد و {found_manual_files} فایل دانلود شده دستی پردازش شد.",
                }

            return {
                "success": True,
                "message": f"عملیات با موفقیت پایان یافت. تعداد {processed_count} قرارداد دریافت شد.",
            }

        except asyncio.CancelledError as ce:
            print(f"[Automation] {ce}")
            await self.teardown_browser()
            return {"success": False, "message": str(ce)}
        except Exception as e:
            print(f"[Automation] Unexpected error: {e}")
            await self.teardown_browser()
            return {"success": False, "message": f"خطای پیش‌بینی نشده: {e}"}


async def scan_and_import_manual_downloads(workspace):
    import os
    from pathlib import Path
    from pdf_reader2 import classify_document, extract_info

    downloads_path = Path.home() / "Downloads"
    desktop_path = Path.home() / "Desktop"

    count = 0
    current_time = time.time()
    max_age_seconds = 3600

    for folder in [downloads_path, desktop_path]:
        if not folder.exists():
            continue

        for file_path in folder.glob("*.pdf"):
            try:
                file_stat = file_path.stat()
                file_age = current_time - max(file_stat.st_mtime, file_stat.st_ctime)

                if file_age < max_age_seconds:
                    full_text = extract_info(str(file_path))
                    doc_type = classify_document(full_text)

                    if doc_type == "CONTRACT" and (
                        "وکالت" in full_text or "وکیل" in full_text
                    ):
                        print(
                            f"[Automation] Found manual contract download: {file_path.name}"
                        )
                        await process_downloaded_pdf(str(file_path), workspace)
                        count += 1

                        try:
                            os.remove(file_path)
                            print(f"[Automation] Deleted original file: {file_path}")
                        except Exception as e:
                            print(f"[Automation] Could not delete original file: {e}")
            except Exception as e:
                print(f"[Automation] Error checking file {file_path.name}: {e}")

    return count


async def process_downloaded_pdf(file_path, workspace):
    from pdf_reader import run_pdf
    from pdf_reader2 import (
        classify_document,
        extract_info,
        extract_shomare_parvande,
        extract_client_number,
    )
    import shutil
    import os
    from web_app import (
        clean_folder_name,
        normalize_persian,
        parse_info_file,
        write_info_file,
        merge_case_numbers_into_info,
        load_scan_cache,
        save_scan_cache,
    )

    filename = os.path.basename(file_path)

    try:
        extracted_data = run_pdf(file_path)
        full_text = extract_info(file_path)
        doc_type = classify_document(full_text)
        client_num = extract_client_number(full_text)
        case_nums = extract_shomare_parvande(file_path)

        target_folder = None
        folder_name = ""

        if case_nums:
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
                        if any(c in client_cases for c in case_nums):
                            target_folder = item_path
                            folder_name = item
                            merge_case_numbers_into_info(info_file, case_nums)
                            break

        pdf_name_to_save = filename

        if not target_folder and doc_type == "CONTRACT" and extracted_data:
            first_name = extracted_data.get("first_name")
            last_name = extracted_data.get("last_name")

            if first_name and last_name:
                pdf_name_to_save = (
                    f"قرارداد الکترونیک وکالت {first_name} {last_name}.pdf"
                )
                base_folder_name = clean_folder_name(f"{first_name} {last_name}")
                folder_name = base_folder_name
                target_folder = os.path.join(workspace, folder_name)

                counter = 2
                while os.path.exists(target_folder):
                    info_file = os.path.join(target_folder, "مشخصات موکل.txt")
                    if os.path.exists(info_file):
                        meta = parse_info_file(info_file)
                        existing_client_num = meta.get("client_number")
                        if (
                            existing_client_num
                            and client_num
                            and existing_client_num == client_num
                        ):
                            break

                    folder_name = f"{base_folder_name} {counter}"
                    target_folder = os.path.join(workspace, folder_name)
                    counter += 1

        if target_folder:
            os.makedirs(target_folder, exist_ok=True)
            os.makedirs(os.path.join(target_folder, "عکس"), exist_ok=True)

            target_pdf_path = os.path.join(target_folder, pdf_name_to_save)
            shutil.copy2(file_path, target_pdf_path)

            info_file_path = os.path.join(target_folder, "مشخصات موکل.txt")
            existing_meta = (
                parse_info_file(info_file_path)
                if os.path.exists(info_file_path)
                else {}
            )

            for k, v in extracted_data.items():
                if v:
                    existing_meta[k] = normalize_persian(str(v))

            write_info_file(info_file_path, existing_meta)

            scan_cache = load_scan_cache(workspace)
            if folder_name in scan_cache:
                del scan_cache[folder_name]
                save_scan_cache(workspace, scan_cache)

            if os.path.exists(file_path):
                os.remove(file_path)

    except Exception as e:
        print(f"[Automation] Error processing PDF {filename}: {e}")
