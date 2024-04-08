import random
import time

import undetected_chromedriver as uc
from message_poster.errors import ListingNotFound, SubmissionError
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import (
    CAPTCHA_TIMEOUT,
    MAX_INPUT_DELAY,
    RENDER_TIMEOUT,
    WAIT_TIMEOUT,
    MessagePoster,
    fill_input,
    interaction_timeout,
    logger,
)


class Website2MessagePoster(MessagePoster):
    def __init__(self, profile, message, listing) -> None:
        self.driver: uc.Chrome = None
        self.profile = profile
        self.message = message
        self.listing: int = listing
        self.settings = profile.website2_settings

    def login(self) -> None:
        "Navigate to website2 login URL and perform the login using credentials"
        self.driver.get("https://www.website2.co.uk/signin/")
        self.driver.implicitly_wait(WAIT_TIMEOUT)
        # From UK geographic location cookie prompt are not always present
        try:
            WebDriverWait(self.driver, RENDER_TIMEOUT / 2).until(
                EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, 'iframe[id="gdpr-consent-notice"]'))
            )
            self.driver.find_element(By.CSS_SELECTOR, 'button[id="save"]').click()
            time.sleep(interaction_timeout())
            self.driver.switch_to.default_content()
            time.sleep(interaction_timeout())
        except Exception:
            logger.info("Cookie not found")
        WebDriverWait(self.driver, RENDER_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[data-testid="email-field-input"]'))
        )
        time.sleep(interaction_timeout())
        # Enter email
        fill_input(
            self.driver.find_element(By.CSS_SELECTOR, 'input[data-testid="email-field-input"]'), self.profile.email
        )
        time.sleep(interaction_timeout())
        # Enter password
        fill_input(
            self.driver.find_element(By.CSS_SELECTOR, 'input[data-testid="password-field"]'), self.profile.password
        )
        # Submit login form
        self.driver.find_element(By.CSS_SELECTOR, 'button[data-testid="signin-button"]').click()
        # Skip info message
        time.sleep(interaction_timeout())
        try:
            self.driver.find_element(By.XPATH, '//*[@id="main-content"]/div/div/div[5]/button/div/div').click()
        except NoSuchElementException:
            pass
        time.sleep(interaction_timeout())

    def navigate(self) -> None:
        "Navigate to the specified URL and handle 404/expired links"
        url = f"https://www.website2.co.uk/for-sale/details/contact/{self.listing}/"
        self.driver.get(url)
        # Expired link case
        if self.driver.current_url.split("/")[-1] == "#expired":
            logger.info(f"The link {url} has been expired")
            self.driver.quit()
            raise ListingNotFound(url)
        try:
            WebDriverWait(self.driver, RENDER_TIMEOUT).until(
                EC.frame_to_be_available_and_switch_to_it(
                    (
                        By.CSS_SELECTOR,
                        "iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']",
                    )
                )
            )
            self.recaptcha_span = self.driver.find_element(
                By.CSS_SELECTOR, 'span[aria-labelledby="recaptcha-anchor-label"]'
            )
            # Wait for the attribute to become 'true'
            WebDriverWait(self.driver, CAPTCHA_TIMEOUT).until(self.is_aria_checked_true)
            # Switch back to the "default content" (that is, out of the iframes)
            self.driver.switch_to.default_content()
        except Exception:
            pass

    def is_aria_checked_true(self, driver: uc.Chrome) -> bool:
        return self.recaptcha_span.get_attribute("aria-checked") == "true"

    def fill_input_form(self) -> None:
        # Toggle checkbox
        if self.settings.is_view_property:
            self.driver.find_element(By.CSS_SELECTOR, 'button[id="interest"]').click()
        time.sleep(interaction_timeout())
        #  Fill  the form
        fill_input(
            self.driver.find_element(By.CSS_SELECTOR, 'input[id="name"]'),
            f"{self.profile.first_name} {self.profile.last_name} ",
            True,
            0,
        )
        fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="email"]'), self.profile.email, True, 0)
        fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="phone"]'), self.profile.phone, True, 0)
        # Post code can be not presented on page
        try:
            fill_input(
                self.driver.find_element(By.CSS_SELECTOR, 'input[id="postcode"]'), self.profile.post_code, True, 0
            )
        except NoSuchElementException:
            pass
        fill_input(self.driver.find_element(By.CSS_SELECTOR, 'textarea[id="message"]'), self.message, delay=0)
        # Situation selection is optional
        try:
            selector = self.driver.find_element(By.CSS_SELECTOR, 'button[aria-haspopup="listbox"]')
            selector.click()
            # downshift-{number}-toggle-button
            target_id = selector.get_attribute("id")
            name, _id = target_id.split("-")[:-2]
            time.sleep(interaction_timeout())
            self.driver.find_element(By.CSS_SELECTOR, f"li[id={name}-{_id}-item-{self.settings.situation}]").click()
            time.sleep(interaction_timeout())
        except NoSuchElementException:
            pass

    @staticmethod
    def fill_input(input_element: WebElement, value: str, clear=False) -> None:
        """fill_input
        Clears and re-enters the given value into the given input element
        """
        if clear:
            input_element.clear()
        input_element.click()
        for c in value:
            input_element.send_keys(c)
            time.sleep(random.uniform(0, MAX_INPUT_DELAY))

    def send_post(self) -> None:
        # Scroll to submit button to be in view
        submit = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        ActionChains(self.driver).move_to_element(submit).perform()
        submit.click()
        time.sleep(RENDER_TIMEOUT)
        if self.driver.current_url.split("/")[-3] != "success":
            self.driver.quit()
            raise SubmissionError("Listing not submitted")

    def close(self) -> None:
        "Wait to form to be processed"
        self.driver.quit()
