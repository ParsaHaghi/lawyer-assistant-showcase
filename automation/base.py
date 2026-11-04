import os
import json
import asyncio
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


class BaseAutomation:
    """
    Base class for automation tasks.
    Provides common functionality like cancellation and Sana login.
    """

    _instance = None

    def __init__(self):
        self.is_cancelled = False
        self.browser = None
        self.context = None
        self.page = None
        BaseAutomation._instance = self

    @classmethod
    def cancel_current(cls):
        """Cancels the currently running automation instance."""
        if cls._instance:
            cls._instance.is_cancelled = True
            return True
        return False

    def check_cancelled(self):
        """Raises an exception if the automation is cancelled."""
        if self.is_cancelled:
            raise asyncio.CancelledError("عملیات توسط کاربر متوقف شد.")

    async def setup_browser(self, headless=False):
        """Initializes the browser and context."""
        self.check_cancelled()
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.context = await self.browser.new_context(accept_downloads=True)
        self.page = await self.context.new_page()

    async def teardown_browser(self):
        """Closes the browser and stops Playwright."""
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright") and self.playwright:
            await self.playwright.stop()

        # Clear the global instance
        if BaseAutomation._instance == self:
            BaseAutomation._instance = None

    def get_sana_credentials(self, base_dir):
        """Reads Sana credentials from sana_config.json if it exists."""
        config_path = os.path.join(base_dir, "sana_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[BaseAutomation] Error reading sana_config.json: {e}")
        return {}

    async def login_to_sana(self, base_dir):
        """
        Navigates to the Sana login page.
        If credentials exist, auto-fills step 1 and clicks next.
        Then waits up to 5 minutes for the user to reach the dashboard.
        """
        self.check_cancelled()

        print("[Automation] Navigating to login page...")
        await self.page.goto("https://lawyer.adliran.ir/Lawyer/Index#/cartableItem")
        self.check_cancelled()

        creds = self.get_sana_credentials(base_dir)
        national_code = creds.get("national_code", "").strip()
        password = creds.get("password", "").strip()

        if national_code and password:
            print("[Automation] Credentials found. Attempting auto-fill step 1...")
            try:
                # Based on standard Adliran/Sana login:
                # Usually there's an input for National Code and Password.
                # Since we have the image in the prompt, there are two inputs and a button "مرحله بعد".
                # National code input might have placeholder "شماره ملی"
                # Password input might have placeholder "رمز شخصی"
                # Button text: "مرحله بعد"

                # Wait for the inputs to be visible. Use more specific visible selectors.
                await self.page.wait_for_selector(
                    "input[type='text']:visible", timeout=15000
                )

                # Get the first visible text input (National Code) and first visible password input (Password)
                text_inputs = await self.page.locator(
                    "input[type='text']:visible"
                ).all()
                pass_inputs = await self.page.locator(
                    "input[type='password']:visible"
                ).all()

                if len(text_inputs) >= 1 and len(pass_inputs) >= 1:
                    # Some sites might use a number input for national code, but usually it's text.
                    # Just in case, let's also try to find by placeholder if it fails, but this should work.
                    await text_inputs[0].fill(national_code)
                    await pass_inputs[0].fill(password)

                    # Click "مرحله بعد"
                    next_btn = (
                        self.page.locator("button:visible")
                        .filter(has_text="مرحله بعد")
                        .first
                    )
                    if await next_btn.count() == 0:
                        # Fallback to any element with that text
                        next_btn = (
                            self.page.locator(":visible")
                            .filter(has_text="مرحله بعد")
                            .last
                        )

                    if await next_btn.count() > 0:
                        await next_btn.click()
                        print("[Automation] Auto-filled credentials and clicked Next.")
                    else:
                        print("[Automation] Could not find 'مرحله بعد' button.")
                else:
                    print(
                        "[Automation] Could not find the required visible input fields."
                    )
            except Exception as e:
                print(f"[Automation] Error during auto-fill step 1: {e}")

        self.check_cancelled()

        print(
            "[Automation] Waiting for user to login and reach the dashboard (کارتابل وکالت)..."
        )
        # Give the user 5 minutes (300000 ms) to enter OTP/Captcha and finish login manually.
        try:
            # We poll the cancellation flag while waiting
            # Instead of a single 300s wait, we wait in chunks to allow cancellation
            wait_time = 300000
            chunk = 1000
            elapsed = 0

            while elapsed < wait_time:
                self.check_cancelled()
                try:
                    # Check if logged in (short timeout)
                    element = await self.page.wait_for_selector(
                        "text=کارتابل وکیل", timeout=chunk
                    )
                    if element:
                        break
                except PlaywrightTimeoutError:
                    elapsed += chunk

            if elapsed >= wait_time:
                raise PlaywrightTimeoutError("Timeout waiting for login.")

            # Add a small delay to ensure page fully loads
            await self.page.wait_for_timeout(3000)
            print("[Automation] Login detected. Starting automation...")
            return True

        except PlaywrightTimeoutError:
            print("[Automation] Timeout waiting for login.")
            return False
