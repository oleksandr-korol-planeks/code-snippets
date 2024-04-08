import logging
import os
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path

import undetected_chromedriver as uc
from django.conf import settings
from selenium.webdriver.remote.webelement import WebElement

ROOT_DIR = Path(__file__).resolve(strict=True).parent.parent.parent.parent
logger = logging.getLogger(__name__)

MAX_INPUT_DELAY = 0.4
"maximum duration of input delay"
WAIT_TIMEOUT = 1
"global wait time for selenium"
MAX_INTERACTION_DELAY = 1
"maximum duration of interaction delay"
RENDER_TIMEOUT = 20
"timeout for rendering wait"
CAPTCHA_TIMEOUT = 110
"maximum time to solve captcha via extension"


def fill_input(input_element: WebElement, value: str, clear=False, delay=MAX_INPUT_DELAY) -> None:
    """fill_input

    Clears and re-enters the given value into the given input element
    """
    if clear:
        input_element.clear()
    input_element.click()
    for c in value:
        input_element.send_keys(c)
        time.sleep(random.uniform(0, delay))


def check_element(element: WebElement) -> None:
    "Method to check element if it is not checked"
    if element.get_attribute("checked") == "true":
        return
    else:
        element.click()
        time.sleep(interaction_timeout())


def interaction_timeout() -> float:
    return random.uniform(0, MAX_INTERACTION_DELAY)


class MessagePoster(ABC):
    def initialize_driver(self) -> None:
        opt = uc.ChromeOptions()
        opt.headless = False
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        opt.add_argument("--disable-gpu")
        opt.add_argument("--no-sandbox")
        opt.add_argument("--disable-dev-shm-usage")
        opt.add_argument("--no-crash-upload")
        opt.add_argument("--disable-crash-reporter")
        opt.add_argument("--disable-infobars")
        opt.add_argument("--disable-dev-shm-usage")
        opt.add_argument("--disable-blink-features=AutomationControlled")
        opt.add_argument("--no-first-run --no-service-autorun --password-store=basic")
        if os.environ.get("PROXY_SERVER"):
            opt.add_argument(f'--proxy-server=https://{os.environ.get("PROXY_SERVER")}')
        opt.add_experimental_option("prefs", prefs)
        """
        Set the subscription key for the extension by visiting this URL.
        You can programmatically import all extension settings using this method.
        To learn more, go to "Export Settings" in the extension popup.
        driver.get(f"https://nopecha.com/setup#{NOPECHA_KEY}")
        """
        opt.add_argument(f"--load-extension={os.path.join(ROOT_DIR, 'extensions', 'NopeCHA-CAPTCHA-Solver')}")
        self.driver = uc.Chrome(options=opt)
        # For elements to be clickable
        self.driver.maximize_window()
        self.driver.get(f'https://nopecha.com/setup#{os.environ.get("NOPECHA_KEY")}')

    @abstractmethod
    def login(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def navigate(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def fill_input_form(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_post(self) -> None:
        raise NotImplementedError

    def run(
        self,
        dry_run: bool = False,
    ) -> None:
        "Run the message poster to send submit form"
        self.initialize_driver()
        self.login()
        self.navigate()
        self.fill_input_form()
        if not dry_run:
            self.send_post()
        self.driver.save_screenshot(f"{settings.MEDIA_ROOT}/{self.listing}.png")
        self.close()
