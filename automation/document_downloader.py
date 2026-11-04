import os
import re
import json
import asyncio
import tempfile
import uuid
import jdatetime
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from automation.base import BaseAutomation

def add_jalali_months(j_date: jdatetime.date, months: int) -> jdatetime.date:
    """Adds a given number of months to a jalali date."""
    y = j_date.year
    m = j_date.month + months
    
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    
    day = j_date.day
    # Ensure the day is valid in the new month
    while True:
        try:
            return jdatetime.date(y, m, day)
        except ValueError:
            day -= 1

class DocumentDownloaderAutomation(BaseAutomation):
    def __init__(self, app=None):
        super().__init__()
        self.status = "INIT"  # INIT, RUNNING, DONE, ERROR
        self.status_message = "در حال آماده‌سازی..."
        self.app = app

    async def run_downloader(self, base_dir: str, client_dir: str, national_id: str, contract_date_str: str):
        """
        Executes the initial document download logic for a specific client.
        """
        self.base_dir = base_dir
        self.client_dir = client_dir
        self.national_id = national_id
        
        try:
            # Parse contract date
            y, m, d = map(int, contract_date_str.split('/'))
            self.current_from_date = jdatetime.date(y, m, d)
        except Exception as e:
            self.status = "ERROR"
            self.status_message = f"فرمت تاریخ قرارداد نامعتبر است: {contract_date_str}"
            return {"success": False, "message": self.status_message}

        try:
            self.status = "RUNNING"
            self.status_message = "در حال باز کردن مرورگر و ورود..."
            
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            await self.setup_browser(headless=False)
            login_success = await self.login_to_sana(project_dir)
            
            if not login_success:
                self.status = "ERROR"
                self.status_message = "زمان انتظار برای ورود پایان یافت."
                return {"success": False, "message": self.status_message}

            self.check_cancelled()

            # Wait for user to complete login and we are on dashboard
            # Try to click the Search Menu -> Search Document
            menu_success = await self.open_search_document_menu()
            if not menu_success:
                self.status = "ERROR"
                self.status_message = "خطا در ورود به منوی جستجوی لایحه."
                return {"success": False, "message": self.status_message}

            self.today_date = jdatetime.date.today()
            
            while self.current_from_date <= self.today_date:
                self.check_cancelled()
                
                # Calculate to_date
                next_to_date = add_jalali_months(self.current_from_date, 6)
                if next_to_date > self.today_date:
                    next_to_date = self.today_date
                
                from_str = self.current_from_date.strftime("%Y/%m/%d")
                to_str = next_to_date.strftime("%Y/%m/%d")
                
                self.status_message = f"در حال جستجو از {from_str} تا {to_str}..."
                print(f"[DocumentDownloader] Searching interval: {from_str} to {to_str}")
                
                await self.perform_search(from_str, to_str, self.national_id)
                
                # Check for table or no results
                has_results = await self.check_search_results()
                
                if has_results:
                    await self.process_search_results()

                # Increment date for next loop
                self.current_from_date = next_to_date + jdatetime.timedelta(days=1)

            self.status = "DONE"
            self.status_message = "عملیات دانلود لوایح موکل با موفقیت به پایان رسید."
            print("[DocumentDownloader] Finished processing all date chunks.")

        except asyncio.CancelledError as e:
            print("[DocumentDownloader] Cancelled.")
            self.status = "ERROR"
            self.status_message = "عملیات متوقف شد."
            return {"success": False, "message": str(e)}
        except Exception as e:
            print(f"[DocumentDownloader] Error: {e}")
            self.status = "ERROR"
            self.status_message = f"خطا: {e}"
            return {"success": False, "message": str(e)}
        finally:
            await self.teardown_browser()

    async def open_search_document_menu(self):
        """Clicks on 'جستجو' then 'جستجوی لایحه' and waits for the form to load."""
        self.status_message = "در حال ورود به منوی جستجوی لایحه..."
        print("[DocumentDownloader] Opening search document menu...")
        
        try:
            # 1. Check if submenu is already visible using strict text match
            submenu_visible = await self.page.evaluate("""() => {
                const keywords = ["جستجوي لايحه", "جستجوی لایحه"];
                const links = Array.from(document.querySelectorAll('a, span, div, li'));
                const target = links.find(el => el.innerText && keywords.includes(el.innerText.trim()) && el.offsetParent !== null);
                return !!target;
            }""")
                    
            # 2. If not visible, expand the parent menu
            if not submenu_visible:
                print("[DocumentDownloader] Submenu not visible. Clicking 'جستجو' parent menu...")
                
                clicked = await self.page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a, span, div, li'));
                    const targets = links.filter(el => el.innerText && el.innerText.trim() === 'جستجو' && el.offsetParent !== null);
                    if (targets.length > 0) {
                        const preferred = targets.find(el => el.tagName.toLowerCase() === 'span' || el.tagName.toLowerCase() === 'a');
                        const target = preferred || targets[0];
                        target.click();
                        return true;
                    }
                    return false;
                }""")
                        
                if not clicked:
                    print("[DocumentDownloader] WARNING: Could not find or click 'جستجو' menu.")
                    return False
                    
                print("[DocumentDownloader] Clicked parent menu. Waiting for animation...")
                await self.page.wait_for_timeout(2000)
            else:
                print("[DocumentDownloader] 'جستجو' menu already expanded.")

            # 3. Click the submenu
            print("[DocumentDownloader] Clicking 'جستجوی لایحه' submenu...")
            submenu_clicked = False
            for i in range(10): # Poll for visibility if animating
                submenu_clicked = await self.page.evaluate("""() => {
                    const keywords = ["جستجوي لايحه", "جستجوی لایحه"];
                    const links = Array.from(document.querySelectorAll('a, span, div, li'));
                    const targets = links.filter(el => el.innerText && keywords.includes(el.innerText.trim()) && el.offsetParent !== null);
                    if (targets.length > 0) {
                        const preferred = targets.find(el => el.tagName.toLowerCase() === 'span' || el.tagName.toLowerCase() === 'a');
                        const target = preferred || targets[0];
                        target.click();
                        return true;
                    }
                    return false;
                }""")
                if submenu_clicked:
                    break
                await self.page.wait_for_timeout(1000)

            if not submenu_clicked:
                print("[DocumentDownloader] WARNING: Could not click 'جستجوی لایحه' submenu.")
                return False

            # 4. Wait for the actual target page to load
            print("[DocumentDownloader] Waiting for Search Page form to load...")
            try:
                # Wait for the unique button that only exists on the Search Document page
                await self.page.locator("button:has-text('بازیابی لایحه با شرایط فوق'), a:has-text('بازیابی لایحه با شرایط فوق')").first.wait_for(state="visible", timeout=15000)
                print("[DocumentDownloader] Search form loaded successfully.")
                return True
            except PlaywrightTimeoutError:
                print("[DocumentDownloader] ERROR: Timed out waiting for search form to load. Not on the correct page.")
                return False
                
        except Exception as e:
            print(f"[DocumentDownloader] Error in open_search_document_menu: {e}")
            return False
            
    async def perform_search(self, from_date: str, to_date: str, national_id: str):
        """Fills the search form and clicks submit."""
        # User requested 1 second wait
        await self.page.wait_for_timeout(1500)
        
        # Wait for form to load
        try:
            await self.page.wait_for_selector("input", timeout=10000)
        except PlaywrightTimeoutError:
            print("[DocumentDownloader] Form not loaded.")
            return

        # Fill Dates
        # Fill Dates and National ID using robust DOM traversal
        try:
            js_fill_logic = """(dates) => {
                function findInput(el) {
                    if (!el) return null;
                    if (el.tagName === 'INPUT') return el;
                    let inp = el.querySelector('input[type="text"], input:not([type])');
                    if (inp) return inp;
                    return null;
                }

                function fillFieldByLabel(labelText, value) {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
                    let node;
                    let matches = [];
                    while (node = walker.nextNode()) {
                        if (node.nodeValue.trim() === labelText) {
                            matches.push(node.parentElement);
                        }
                    }
                    
                    if (matches.length === 0) return false;
                    
                    // Try each match until we successfully find and fill an input
                    for (let labelEl of matches) {
                        let inp = null;
                        
                        // 1. Check parent for a single input
                        if (labelEl.parentElement) {
                            let inputs = labelEl.parentElement.querySelectorAll('input[type="text"], input:not([type])');
                            if (inputs.length === 1) inp = inputs[0];
                        }
                        
                        // 2. Check siblings of label (next first, since DOM order is label -> input even in RTL)
                        if (!inp) inp = findInput(labelEl.nextElementSibling);
                        if (!inp) inp = findInput(labelEl.previousElementSibling);
                        
                        // 3. Check siblings of parent
                        let parent = labelEl.parentElement;
                        if (!inp && parent) {
                            inp = findInput(parent.nextElementSibling);
                            if (!inp) inp = findInput(parent.previousElementSibling);
                        }
                        
                        // 4. Check siblings of grandparent
                        let grandparent = parent ? parent.parentElement : null;
                        if (!inp && grandparent) {
                            inp = findInput(grandparent.nextElementSibling);
                            if (!inp) inp = findInput(grandparent.previousElementSibling);
                        }
                        
                        // Check if the found input is visually hidden or read-only (optional safety check)
                        if (inp) {
                            inp.value = value;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                            return true; // Successfully filled
                        }
                    }
                    return false;
                }

                fillFieldByLabel('زمان ثبت از', dates.from);
                fillFieldByLabel('تا', dates.to);
                fillFieldByLabel('شناسه/شماره ملی', dates.nid);
            }"""
            
            await self.page.evaluate(js_fill_logic, {"from": from_date, "to": to_date, "nid": national_id})
        except Exception as e:
            print(f"[DocumentDownloader] Error filling form: {e}")

        await self.page.wait_for_timeout(500)

        # Click Search Button (Green button: بازیابی لایحه با شرایط فوق)
        try:
            btn = self.page.locator("button:has-text('بازیابی لایحه با شرایط فوق'), a:has-text('بازیابی لایحه با شرایط فوق')").first
            if await btn.count() > 0:
                await btn.click()
            else:
                # Try via JS
                await self.page.evaluate("""() => {
                    const buttons = Array.from(document.querySelectorAll('button, a, .btn'));
                    const target = buttons.find(b => b.innerText && b.innerText.includes('بازیابی لایحه با شرایط فوق'));
                    if (target) target.click();
                }""")
        except Exception as e:
            print(f"[DocumentDownloader] Error clicking search button: {e}")

        # Wait for loading mask to disappear or table to appear
        await self.page.wait_for_timeout(3000)

    async def check_search_results(self):
        """Checks if there are results in the table."""
        try:
            # Check for empty message
            empty_msg = self.page.locator("text='رکوردی یافت نشد', text='هیچ موردی یافت نشد', .dataTables_empty")
            if await empty_msg.count() > 0 and await empty_msg.is_visible():
                print("[DocumentDownloader] No results found for this date range.")
                return False
                
            table = self.page.locator("table")
            if await table.count() > 0:
                rows = await table.locator("tbody tr").all()
                if len(rows) > 0 and not "هیچ موردی یافت نشد" in await rows[0].inner_text():
                    return True
            return False
        except Exception:
            return False

    async def process_search_results(self):
        """Downloads all documents in the search results."""
        has_next_page = True

        while has_next_page:
            self.check_cancelled()
            
            # Re-locate rows
            rows = await self.page.locator("table tbody tr").all()
            row_count = len(rows)
            print(f"[DocumentDownloader] Found {row_count} rows on current page.")

            for i in range(row_count):
                self.check_cancelled()
                # Must re-query rows in case of navigation
                rows = await self.page.locator("table tbody tr").all()
                if i >= len(rows):
                    continue
                row = rows[i]
                
                document_title = await self._extract_document_title(row)
                print(f"[DocumentDownloader] Processing document: {document_title}")
                
                await row.click()
                await self.page.wait_for_timeout(3000)
                
                await self.process_details_page(document_title)
                
                # Navigate back to search results
                print(f"[DocumentDownloader] Returning to list...")
                await self._click_sidebar_search_menu()
                await self.page.wait_for_timeout(4000)

            # Check next page
            next_btn = self.page.locator(
                "a.paginate_button.next:not(.disabled), li.next:not(.disabled) a, button:has-text('بعدی'):not([disabled])"
            ).first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                print("[DocumentDownloader] Going to next page...")
                await next_btn.click()
                await self.page.wait_for_timeout(3000)
            else:
                has_next_page = False

    async def _extract_document_title(self, row):
        try:
            tds = await row.locator("td").all()
            headers = await self.page.locator("table thead th").all_inner_texts()
            doc_title_index = -1
            for i, header in enumerate(headers):
                if "عنوان مدرک" in header or "نوع لایحه" in header or "موضوع لایحه" in header:
                    doc_title_index = i
                    break

            if doc_title_index != -1 and len(tds) > doc_title_index:
                title = await tds[doc_title_index].inner_text()
                return title.strip()
            elif len(tds) > 1:
                return await tds[-2].inner_text()
        except Exception:
            pass
        return "سند"

    async def _click_sidebar_search_menu(self):
        """Navigate back to the search results list."""
        success = await self.open_search_document_menu()
        if not success:
            raise Exception("Failed to navigate back to search results menu.")

    async def process_details_page(self, document_title):
        """Processes the details page, extracts request, and downloads the PDF."""
        request_text = "بدون عنوان"
        try:
            khast_element = self.page.locator(
                "td:has-text('خواسته') + td, th:has-text('خواسته') + td, div:has-text('خواسته') + div, span:has-text('خواسته') + span"
            ).first
            if await khast_element.count() > 0:
                raw_text = await khast_element.inner_text()
                request_text = re.sub(r"^\d+\s*-\s*", "", raw_text.strip())
            else:
                tds = await self.page.locator("td").all()
                for i, td in enumerate(tds):
                    text = await td.inner_text()
                    if "خواسته" in text.strip() and i + 1 < len(tds):
                        raw_text = await tds[i + 1].inner_text()
                        request_text = re.sub(r"^\d+\s*-\s*", "", raw_text.strip())
                        break
        except Exception:
            pass

        print(f"[DocumentDownloader] Extracted request: {request_text}")
        file_name_base = f"{document_title} {request_text}".strip()

        # Click Print
        print("[DocumentDownloader] Looking for 'چاپ' button...")
        try:
            print_btn = self.page.get_by_text("چاپ اوليه", exact=False).first
            if await print_btn.count() == 0:
                 print_btn = self.page.get_by_text("چاپ", exact=False).first
            await print_btn.wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            print("[DocumentDownloader] Could not find print button. Skipping.")
            return

        try:
            download_promise = asyncio.create_task(self.page.wait_for_event("download", timeout=15000))
            page_promise = asyncio.create_task(self.context.wait_for_event("page", timeout=15000))

            await print_btn.click(force=True)

            done, pending = await asyncio.wait(
                [page_promise, download_promise],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=60.0,
            )

            for p in pending:
                p.cancel()

            self.check_cancelled()
            downloads_dir = tempfile.gettempdir()

            file_path = None

            if download_promise in done and not download_promise.exception():
                download = download_promise.result()
                file_path = os.path.join(downloads_dir, f"doc_{uuid.uuid4().hex[:8]}.pdf")
                await download.save_as(file_path)
            elif page_promise in done and not page_promise.exception():
                new_page = page_promise.result()
                try:
                    await new_page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                try:
                    await new_page.evaluate("window.print = () => {}")
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

                file_path = os.path.join(downloads_dir, f"doc_{uuid.uuid4().hex[:8]}.pdf")
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
                except Exception as cdp_err:
                    print(f"[DocumentDownloader] CDP print failed: {cdp_err}")
                await new_page.close()
            else:
                try:
                    close_btn = self.page.locator("button, a").filter(has_text="بستن").first
                    if await close_btn.count() > 0:
                        await close_btn.click(force=True)
                except Exception:
                    pass

            if file_path and os.path.exists(file_path):
                self._save_to_client_dir(file_path, file_name_base)

        except Exception as e:
            print(f"[DocumentDownloader] Error during download: {e}")

    def _save_to_client_dir(self, temp_path, file_name_base):
        safe_name = re.sub(r'[\\/*?:"<>|]', "", file_name_base)
        final_name = f"{safe_name}.pdf"

        target_path = os.path.join(self.client_dir, final_name)
        counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(self.client_dir, f"{safe_name} ({counter}).pdf")
            counter += 1

        os.rename(temp_path, target_path)
        print(f"[DocumentDownloader] Saved file to {target_path}")
