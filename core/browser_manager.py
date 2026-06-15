"""
core/browser_manager.py
-----------------------
Handles browser driver initialization for Chrome, Edge, and Brave.

Chrome & Brave use undetected_chromedriver (uc) for maximum stealth.
Edge falls back to regular Selenium + EdgeChromiumDriverManager.
Persistent browser profiles keep WhatsApp logged-in between sessions.
"""

import os
import random
import subprocess
from typing import Optional

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from config import BROWSER_PROFILES_DIR, BRAVE_PATHS
from utils.logger import get_logger


# ── Chrome registry paths to check (user install, 32-on-64, and Update keys) ──
_CHROME_REGISTRY_PATHS = [
    r"Software\Google\Chrome\BLBeacon",                                      # user install
    r"Software\Wow6432Node\Google\Chrome\BLBeacon",                          # 32-bit on 64-bit OS
    r"Software\Google\Update\Clients\{8A69D345-D564-463c-AFF1-A69D9E530F96}",  # Google Update key
]

_CHROME_SUBPROCESS_NAMES = [
    "chrome",
    "google-chrome",
    "google-chrome-stable",
]

_CHROME_FALLBACK_VERSION = 134   # update when a new major version is released


def get_chrome_version() -> int:
    """Detect the installed Chrome major version.

    Tries (in order):
    1. Multiple Windows registry paths under HKCU and HKLM.
    2. Subprocess call to ``chrome --version`` (Linux / PATH-accessible Windows).
    3. Returns ``_CHROME_FALLBACK_VERSION`` if everything fails.
    """
    if os.name == "nt":
        import winreg
        for reg_path in _CHROME_REGISTRY_PATHS:
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, reg_path) as key:
                        version, _ = winreg.QueryValueEx(key, "version")
                        return int(version.split(".")[0])
                except Exception:
                    continue

        # Subprocess fallback on Windows (Chrome on PATH)
        try:
            result = subprocess.check_output(
                ["chrome", "--version"], stderr=subprocess.DEVNULL, timeout=5
            )
            return int(result.decode().split()[-1].split(".")[0])
        except Exception:
            pass

    else:
        # Linux / macOS
        for exe in _CHROME_SUBPROCESS_NAMES:
            try:
                result = subprocess.check_output(
                    [exe, "--version"], stderr=subprocess.DEVNULL, timeout=5
                )
                return int(result.decode().split()[-1].split(".")[0])
            except Exception:
                continue

    return _CHROME_FALLBACK_VERSION


# ── Rotating realistic user-agents (Chrome 124–134, Windows 10/11) ────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.6834.160 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.6367.207 Safari/537.36",
]

logger = get_logger(__name__)

# ── Clipboard backend: use xclip on Linux ─────────────────────────────────────
if os.name != "nt":
    try:
        import pyperclip
        pyperclip.set_clipboard("xclip")
    except Exception:
        pass  # pyperclip may not be importable yet; browser_manager loads early

# ── Running inside Docker / Render? ───────────────────────────────────────────
_IS_LINUX = os.name != "nt"
_IN_PRODUCTION = os.environ.get("PYTHON_ENV", "").lower() == "production"


class BrowserManager:
    """
    Factory + lifecycle manager for Selenium WebDriver instances.

    Usage:
        bm = BrowserManager(browser="Chrome", headless=False)
        driver = bm.create_driver()
        ...
        bm.quit()
    """

    def __init__(self, browser: str = "Chrome", headless: bool = False, proxy: Optional[str] = None):
        """
        Args:
            browser:  One of "Chrome", "Edge", "Brave".
            headless: Run browser without a visible window.
            proxy:    Optional proxy, format: "http://user:pass@host:port" or "host:port"
        """
        self.browser = browser.strip().title()
        self.headless = headless
        self.proxy = proxy
        self.driver: Optional[webdriver.Remote] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def create_driver(self) -> webdriver.Remote:
        """
        Instantiate and return the Selenium WebDriver.
        The driver is also stored as self.driver.
        """
        logger.info("Creating %s WebDriver (headless=%s)", self.browser, self.headless)

        if self.browser == "Chrome":
            self.driver = self._create_chrome()
        elif self.browser == "Edge":
            self.driver = self._create_edge()
        elif self.browser == "Brave":
            self.driver = self._create_brave()
        else:
            raise ValueError(f"Unsupported browser: {self.browser}")

        # For better control (especially authenticated residential proxies), use selenium-wire in BrowserManager.create_driver
        if self.proxy and "@" in self.proxy:
            # We already configured proxy in options, but if they want selenium-wire specifically here
            pass

        self.driver.set_page_load_timeout(60)
        logger.info("%s driver ready.", self.browser)
        return self.driver

    def quit(self):
        """Gracefully close the browser and release the driver."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Browser closed.")
            except Exception as e:
                logger.warning("Error closing browser: %s", e)
            finally:
                self.driver = None

    def is_alive(self) -> bool:
        """Return True if the WebDriver session is still responsive.

        An *invalid session id* or any WebDriverException means Chrome has
        crashed or been closed externally.  Callers should abort immediately
        instead of issuing further commands.
        """
        if not self.driver:
            return False
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    # ── Private helpers ────────────────────────────────────────────────────────

    def _common_options(self, options, *, is_uc: bool = False) -> None:
        """
        Apply stealth Chrome options.
        is_uc=True  → skip experimental_option calls (uc manages those itself).
        """
        # Core stability (required on Linux / Docker)
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-infobars")

        # Linux / Docker extras
        if _IS_LINUX:
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--disable-setuid-sandbox")
            # Expose debugging port so web_app.py can take screenshots
            options.add_argument("--remote-debugging-port=9222")
            # Memory optimisation for free-tier (512 MB RAM)
            options.add_argument("--js-flags=--max-old-space-size=256")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-breakpad")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-translate")
            options.add_argument("--metrics-recording-only")
            options.add_argument("--mute-audio")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--safebrowsing-disable-auto-update")

        # Stealth: fingerprint suppression
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-plugins-discovery")
        options.add_argument("--log-level=3")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--password-store=basic")

        # Disable site isolation (reduces fingerprint surface)
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--disable-site-isolation-trials")

        # Rotating real user-agent
        options.add_argument(f"--user-agent={random.choice(_USER_AGENTS)}")

        # Real device fingerprints
        options.add_argument("--disable-webrtc")
        options.add_argument("--disable-battery-status-api")
        options.add_argument("--disable-client-side-phishing-detection")

        # Only add experimental options when NOT using undetected_chromedriver
        if not is_uc:
            options.add_argument("--disable-extensions")
            options.add_experimental_option(
                "excludeSwitches", ["enable-automation", "enable-logging"]
            )
            options.add_experimental_option("useAutomationExtension", False)

        if self.headless:
            options.add_argument("--headless=new")

        if self.proxy:
            if "@" in self.proxy:  # authenticated
                options.add_argument(f'--proxy-server={self.proxy}')
            else:
                options.add_argument(f'--proxy-server=http://{self.proxy}')

    def _profile_path(self, browser_name: str) -> str:
        path = BROWSER_PROFILES_DIR / browser_name.lower()
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _kill_zombie_processes(self, profile_path: str):
        """Kill any existing Chrome processes using this profile to prevent locking."""
        if os.name == 'nt':
            try:
                cmd = f"Get-CimInstance Win32_Process | Where-Object {{$_.Name -eq 'chrome.exe' -and $_.CommandLine -match 'browser_profiles'}} | Invoke-CimMethod -MethodName Terminate"
                subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=5)
            except Exception as e:
                logger.debug("Failed to clean up zombie processes: %s", e)

    def _create_chrome(self) -> uc.Chrome:
        opts = uc.ChromeOptions()
        self._common_options(opts, is_uc=True)
        profile_path = self._profile_path('chrome')
        opts.add_argument(f"--user-data-dir={profile_path}")

        # Ensure no old processes are locking this profile directory
        self._kill_zombie_processes(profile_path)

        # On Linux (Docker/Render) set DISPLAY so Chrome can render via Xvfb
        if _IS_LINUX:
            os.environ.setdefault("DISPLAY", ":99")

        # use_subprocess causes issues in some Docker environments on Linux
        use_subprocess = not _IS_LINUX

        driver = uc.Chrome(
            options=opts,
            use_subprocess=use_subprocess,
            version_main=get_chrome_version(),
        )

        import selenium_stealth
        selenium_stealth.stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        return driver

    def _create_edge(self) -> webdriver.Edge:
        opts = EdgeOptions()
        self._common_options(opts)
        opts.add_argument(f"--user-data-dir={self._profile_path('edge')}")
        service = EdgeService(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=opts)

    def _create_brave(self) -> uc.Chrome:
        brave_exe = self._find_brave()
        if not brave_exe:
            raise FileNotFoundError(
                "Brave browser not found. "
                "Make sure Brave is installed or add its path to BRAVE_PATHS in config.py"
            )

        opts = uc.ChromeOptions()
        opts.binary_location = brave_exe
        self._common_options(opts, is_uc=True)
        opts.add_argument(f"--user-data-dir={self._profile_path('brave')}")

        # uc handles chromedriver download — auto-detect version
        if self.proxy and "@" in self.proxy:
            from seleniumwire import undetected_chromedriver as uc_wire
            proxy_options = {
                'proxy': {
                    'http': self.proxy,
                    'https': self.proxy,
                    'no_proxy': 'localhost,127.0.0.1'
                }
            }
            driver = uc_wire.Chrome(options=opts, use_subprocess=True, seleniumwire_options=proxy_options, version_main=get_chrome_version())
        else:
            driver = uc.Chrome(options=opts, use_subprocess=True, version_main=get_chrome_version())
            
        import selenium_stealth
        selenium_stealth.stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        
        return driver

    @staticmethod
    def _find_brave() -> Optional[str]:
        for path in BRAVE_PATHS:
            if os.path.isfile(path):
                return path
        return None
