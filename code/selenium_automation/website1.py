import platform
import random
import time
from typing import List
from urllib.parse import parse_qs, urlparse

import undetected_chromedriver as uc
from message_poster.errors import AccountDisabled, AccountRequireAction, ListingNotFound, LoginError, SubmissionError
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.window import WindowTypes
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import (
    CAPTCHA_TIMEOUT,
    MAX_INPUT_DELAY,
    RENDER_TIMEOUT,
    WAIT_TIMEOUT,
    MessagePoster,
    check_element,
    interaction_timeout,
    logger,
)


class Website1MessagePoster(MessagePoster):
    def __init__(self, profile, message, listing) -> None:
        self.driver: uc.Chrome = None
        self.profile = profile
        self.message = message
        self.listing: int = listing
        self.settings = profile.website1_settings

    def login(self) -> None:
        self.driver.implicitly_wait(WAIT_TIMEOUT)
        "Perform the login using credentials"
        self.driver.get("https://www.website1.co.uk/login.html")
        # From UK geographic location cookie prompt are not present
        try:
            cookies_button = WebDriverWait(self.driver, RENDER_TIMEOUT / 2).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#onetrust-accept-btn-handler"))
            )
            cookies_button.click()
        except Exception:
            logger.info("Cookie not found")
        time.sleep(interaction_timeout())
        # Enter email
        self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="email-input"]'), self.profile.email)
        # Submit email
        self.driver.find_element(By.CSS_SELECTOR, 'button[id="emailSubmit"]').click()
        time.sleep(interaction_timeout())
        # Check form by submit button
        email_submit = self.driver.find_element(By.CSS_SELECTOR, 'button[id="submit"]')
        # Case of issues with account
        if email_submit.accessible_name == "Create an account":
            logger.error(f"Account {self.profile.email} is not registered/banned")
            self.driver.quit()
            raise AccountDisabled(f"Account {self.profile.email} is not registered/banned/disabled")
        # Submit enter password
        time.sleep(interaction_timeout())
        self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="password-input"]'), self.profile.password)
        # Get submit button and check if it enabled
        submit = self.driver.find_element(By.CSS_SELECTOR, 'button[id="submit"]')
        time.sleep(interaction_timeout())
        # Change button to enabled if it disabled
        if submit.get_attribute("disabled") is True:
            # Change login button to enabled
            self.driver.execute_script("arguments[0].disabled = false", submit)
        submit.click()
        # Wait for login to complete to proceed by waiting for the user details page to load
        try:
            WebDriverWait(self.driver, RENDER_TIMEOUT * 3).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(@href,'/user/details.html')]"))
            )
        except TimeoutException:
            self.driver.quit()
            raise LoginError(f"Account {self.profile.email} Cannot enter profile page")

    def navigate(self) -> None:
        "Navigate to the specified URL and handle 404/expired links"
        # Disabling Nopecha after first verification
        self.driver.get("chrome://extensions/")
        extensions = self.driver.find_element(By.CSS_SELECTOR, "extensions-manager")
        extensions.shadow_root.find_element(By.ID, "viewManager").find_element(
            By.ID, "items-list"
        ).shadow_root.find_element(By.CSS_SELECTOR, "extensions-item").shadow_root.find_element(
            By.ID, "enableToggle"
        ).click()
        url = f"https://www.website1.co.uk/property-for-sale/contactBranch.html?propertyId={self.listing}"
        self.driver.get(url)
        try:
            _id = parse_qs(urlparse(url).query)["propertyId"][0]
        except KeyError:
            logger.error(f"The link {url} has been expired")
            self.driver.quit()
            raise ListingNotFound(url)
        #  Missing pages can be
        #  https://www.website1.co.uk/properties/123#/?channel=RES_BUY
        #  or valid url with `Error Page` title
        if urlparse(self.driver.current_url).path == f"/properties/{_id}" or self.driver.title == "Error Page":
            logger.error(f"The link {url} has been expired")
            self.driver.quit()
            raise ListingNotFound(url)

    def fill_input_form(self) -> None:
        "Fill form with message data"
        # Wait for the form to load
        WebDriverWait(self.driver, RENDER_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'button[data-test="submitButton"]'))
        )
        self.clear_inputs(
            [
                self.driver.find_element(By.CSS_SELECTOR, 'input[id="firstName"]'),
                self.driver.find_element(By.CSS_SELECTOR, 'input[id="lastName"]'),
                self.driver.find_element(By.CSS_SELECTOR, 'input[id="phone.number"]'),
                self.driver.find_element(By.CSS_SELECTOR, 'input[id="email"]'),
            ],
        )
        self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="firstName"]'), self.profile.first_name)
        time.sleep(interaction_timeout())
        self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="lastName"]'), self.profile.last_name)
        time.sleep(interaction_timeout())
        self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="phone.number"]'), self.profile.phone)
        time.sleep(interaction_timeout())
        self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="email"]'), self.profile.email)
        time.sleep(interaction_timeout())
        message_field = self.driver.find_element(By.CSS_SELECTOR, 'textarea[id="comments"]')
        if self.driver.find_element(By.CSS_SELECTOR, 'textarea[id="manualAddress"]').text != self.profile.address:
            country_list = self.driver.find_elements(By.CSS_SELECTOR, 'option[value="HR"]')
            for country in country_list:
                if country.text == "United Kingdom":
                    country.click()
                    break
            time.sleep(interaction_timeout())
            # Entering postcode from template
            self.clear_inputs([self.driver.find_element(By.CSS_SELECTOR, 'input[id="postcode"]')])
            self.fill_input(self.driver.find_element(By.CSS_SELECTOR, 'input[id="postcode"]'), self.profile.post_code)
            message_field.click()
            time.sleep(interaction_timeout())
            # Selecting manual address entry
            self.driver.find_element(By.CSS_SELECTOR, 'button[class="addressPicker_notListed"]').click()
            time.sleep(interaction_timeout())
            self.fill_input(
                self.driver.find_element(By.CSS_SELECTOR, 'textarea[id="manualAddress"]'), self.profile.address
            )
            time.sleep(interaction_timeout())
        # Fill message field
        self.fill_input(message_field, self.message)
        time.sleep(interaction_timeout())
        # After filling standard data proceed to listing specific data
        self.listing_specific_data()

    def fill_input(self, input_element: WebElement, value: str, clear=False) -> None:
        """fill_input
        Clears and re-enters the given value into the given input element
        In website1 platform we also handle click
        """

        if clear:
            input_element.clear()
        input_element.click()
        for c in value:
            input_element.send_keys(c)
            time.sleep(random.uniform(0, MAX_INPUT_DELAY))

    def listing_specific_data(self) -> None:
        "Extract listing type from url and perform specific actions"
        variant = self.driver.current_url.split("/")[3]
        # When start filling extra data we should scroll to submit button for all elements to be clickable
        submit_button = self.driver.find_element(By.CSS_SELECTOR, 'button[data-test="submitButton"]')
        ActionChains(self.driver).move_to_element(submit_button).perform()
        # Toggle more details
        time.sleep(interaction_timeout())
        if self.settings.is_more_details:
            check_element(self.driver.find_element(By.CSS_SELECTOR, 'input[id="moreDetailsRequested"]'))
        if self.settings.is_view_property:
            self.driver.find_element(By.CSS_SELECTOR, 'input[id="toViewProperty"]').click()
            time.sleep(interaction_timeout())
        match variant:
            case "commercial-property-for-sale":
                """options:
                - as surveyor/agent `surveyor_agent`
                - as investor/developer `investor_developer`
                - as tenant/buyer `tenant_buyer`
                - other `other`
                """
                self.driver.find_element(By.CSS_SELECTOR, 'select[id="enquirerType"]').click()
                time.sleep(interaction_timeout())
                self.driver.find_element(
                    By.CSS_SELECTOR, f'#enquirerType option[value="{self.settings.requiring_as.lower()}"]'
                ).click()
                time.sleep(interaction_timeout())
            case "commercial-property-to-let":
                self.driver.find_element(By.CSS_SELECTOR, 'select[id="enquirerType"]').click()
                """options:
                - as surveyor/agent `surveyor_agent`
                - as investor/developer `investor_developer`
                - as tenant/buyer `tenant_buyer`
                - other `other`
                """
                time.sleep(interaction_timeout())
                self.driver.find_element(
                    By.CSS_SELECTOR, f'#enquirerType option[value="{self.settings.requiring_as.lower()}"]'
                ).click()
            case "property-for-sale":
                # Select property to sell selector
                self.driver.find_element(By.CSS_SELECTOR, 'select[id="sellingSituationType"]').click()
                time.sleep(interaction_timeout())
                """options:
                - No `no`
                - Yes, it is not yen on market `pr_not_on_mark`
                - Yes, it is the market already `pr_on_mark`
                - Yes, it is under offer `pr_under_off`
                - Yes, it is already exchanged `pr_exchanged`
                """
                self.driver.find_element(
                    By.CSS_SELECTOR, f'#sellingSituationType option[value="{self.settings.property_to_sell.lower()}"]'
                ).click()
                time.sleep(interaction_timeout())
                # Select property to let selector
                self.driver.find_element(By.CSS_SELECTOR, 'select[id="rentingSituationType"]').click()
                time.sleep(interaction_timeout())
                """options:
                - No `no`
                - Not yet, I intend to buy to let `pr_rent_to_purchase`
                - Yes, it is available to let not `pr_rent_available`
                - Yes, it will be available to let soon `pr_rent_available_soon`
                - Yes, it is currently occupied `pr_rent_occupied`
                """
                self.driver.find_element(
                    By.CSS_SELECTOR, f'#rentingSituationType option[value="{self.settings.property_to_let.lower()}"]'
                ).click()
                time.sleep(interaction_timeout())
                # Valuation checkbox
                if self.settings.is_valuation_requested:
                    self.driver.find_element(By.CSS_SELECTOR, 'input[id="valuationRequested"]').click()
                time.sleep(interaction_timeout())
            case "new-homes-to-sell":
                if self.settings.is_part_exchange_requested:
                    self.driver.find_element(By.CSS_SELECTOR, 'input[id="partExchangeRequested"]').click()
                time.sleep(interaction_timeout())
            case _:
                time.sleep(interaction_timeout())

    def clear_inputs(self, elements: List[WebElement]) -> None:
        "Clear inputs with direct keystrokes .clear() not working"
        for element in elements:
            element.click()
            if platform.system() == "Darwin":
                element.send_keys(Keys.COMMAND + "a")
            else:
                element.send_keys(Keys.CONTROL + "a")
            element.send_keys(Keys.BACK_SPACE)
            time.sleep(interaction_timeout())

    def send_post(self) -> None:
        "Send the post message on website1 and pass captcha"
        # Enable NopeCha before submitting
        self.driver.switch_to.new_window(WindowTypes.TAB)
        self.driver.get("chrome://extensions/")
        extensions = self.driver.find_element(By.CSS_SELECTOR, "extensions-manager")
        extensions.shadow_root.find_element(By.ID, "viewManager").find_element(
            By.ID, "items-list"
        ).shadow_root.find_element(By.CSS_SELECTOR, "extensions-item").shadow_root.find_element(
            By.ID, "enableToggle"
        ).click()
        # Switch back to form submission
        self.driver.switch_to.window(self.driver.window_handles[0])
        self.driver.find_element(By.CSS_SELECTOR, 'button[data-test="submitButton"]').click()
        # Wait for captcha to be solved if present
        try:
            WebDriverWait(self.driver, CAPTCHA_TIMEOUT).until(
                EC.frame_to_be_available_and_switch_to_it(
                    (
                        By.CSS_SELECTOR,
                        "iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']",
                    )
                )
            )
        except TimeoutException:
            pass
        # Case for activation email
        try:
            WebDriverWait(self.driver, RENDER_TIMEOUT).until(
                EC.frame_to_be_available_and_switch_to_it(
                    (
                        By.CSS_SELECTOR,
                        "iframe[id='email-verification-iframe']",
                    )
                )
            )
            time.sleep(interaction_timeout())
            self.driver.find_element(By.CSS_SELECTOR, 'button[data-test="checkEmailButton"]').click()
            time.sleep(interaction_timeout())
            self.driver.quit()
            raise AccountRequireAction("Activation email was sent")
        except Exception:
            pass
        # Check for confirmation banner
        time.sleep(RENDER_TIMEOUT * 2)
        try:
            self.driver.find_element(By.CSS_SELECTOR, 'div[data-test="confirmationBanner"]')
        except NoSuchElementException:
            self.driver.quit()
            raise SubmissionError("Listing not submitted")

    def close(self) -> None:
        "Close the browser window and perform any necessary cleanup"
        self.driver.quit()
