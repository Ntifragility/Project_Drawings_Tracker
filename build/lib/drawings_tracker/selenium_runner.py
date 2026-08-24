from __future__ import annotations

import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class SeleniumRunner:
    def __init__(self, download_dir: str | Path, headless: bool = True) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.driver = self._build_driver(headless=headless)

    def _build_driver(self, headless: bool) -> webdriver.Chrome:
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        if headless:
            options.add_argument("--headless=new")
        prefs = {
            "download.default_directory": str(self.download_dir),
            "download.prompt_for_download": False,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)
        return webdriver.Chrome(options=options)

    def _wait_for_clickable(self, selector: str, timeout: int = 25):
        return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))

    def _wait_for_presence(self, selector: str, timeout: int = 25):
        return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))

    def _has_visible_error_message(self) -> bool:
        keywords = ("error", "fallido", "no acceso", "incorrect", "credenciales")
        for element in self.driver.find_elements(By.XPATH, "//*[contains(normalize-space(.), '')]"):
            try:
                if not element.is_displayed():
                    continue
                text = element.text.lower()
                if any(keyword in text for keyword in keywords):
                    return True
            except Exception:
                continue
        return False

    def _is_login_form_present(self) -> bool:
        for element_id in ("txtUserExterno", "txtPasswordExterno", "btnAl"):
            try:
                element = self.driver.find_element(By.ID, element_id)
                if element.is_displayed() and element.is_enabled():
                    return True
            except Exception:
                continue
        return False

    def _wait_for_page_ready(self, timeout: int = 15) -> None:
        WebDriverWait(self.driver, timeout).until(
            lambda driver: driver.execute_script("return document.readyState") == "complete"
        )

    def _click_element(self, element) -> None:
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        try:
            element.click()
        except Exception:
            try:
                ActionChains(self.driver).move_to_element(element).click().perform()
            except Exception:
                self.driver.execute_script("arguments[0].click();", element)

    def _find_first_element(self, selectors: list[tuple[By, str]], timeout: float = 2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.driver.switch_to.default_content()
            for by, value in selectors:
                try:
                    elements = self.driver.find_elements(by, value)
                except Exception:
                    elements = []
                if elements:
                    for element in elements:
                        try:
                            if element.is_displayed() and element.is_enabled():
                                return element
                        except Exception:
                            continue

            try:
                frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            except Exception:
                frames = []

            for frame in frames:
                try:
                    self.driver.switch_to.frame(frame)
                    for by, value in selectors:
                        try:
                            elements = self.driver.find_elements(by, value)
                        except Exception:
                            elements = []
                        if elements:
                            for element in elements:
                                try:
                                    if element.is_displayed() and element.is_enabled():
                                        return element
                                except Exception:
                                    continue
                except Exception:
                    pass
                finally:
                    self.driver.switch_to.parent_frame()

            time.sleep(0.1)

        raise TimeoutException("Could not find a matching element in the page or embedded frames")

    def _find_login_button(self):
        candidates = [
            (By.ID, "btnAl"),
            (By.CSS_SELECTOR, "button[id='btnAl']"),
            (By.XPATH, "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ingresar')]"),
            (By.XPATH, "//input[@type='submit' and contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ingresar')]"),
            (By.XPATH, "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ingresar')]"),
        ]
        return self._find_first_element(candidates, timeout=2.0)

    def login(self, url: str, username: str, password: str) -> None:
        self.driver.get(url)
        wait = WebDriverWait(self.driver, 20)
        initial_url = self.driver.current_url

        try:
            externo_tab = wait.until(EC.element_to_be_clickable((By.ID, "headerExterno")))
            print("Clicking 'Externo' tab...")
            self._click_element(externo_tab)
        except TimeoutException as e:
            raise RuntimeError(f"Could not find or click 'Externo' tab (ID: headerExterno): {e}")

        try:
            username_field = wait.until(EC.visibility_of_element_located((By.ID, "txtUserExterno")))
            username_field.clear()
            username_field.send_keys(username)
            print(f"Username entered: {username}")
        except TimeoutException as e:
            raise RuntimeError(f"Could not locate username field: {e}")

        try:
            password_field = wait.until(EC.visibility_of_element_located((By.ID, "txtPasswordExterno")))
            password_field.clear()
            password_field.send_keys(password)
            print(f"Password entered ({len(password)} characters)")
        except TimeoutException as e:
            raise RuntimeError(f"Could not locate password field: {e}")

        try:
            ingresar_button = self._find_login_button()
            print("Clicking 'Ingresar' button...")
            self._click_element(ingresar_button)
        except TimeoutException as e:
            try:
                password_field.send_keys(Keys.ENTER)
                print("Pressed Enter on password field as fallback")
            except Exception as fallback_error:
                raise RuntimeError(f"Could not find or click 'Ingresar' button: {e}; fallback error: {fallback_error}")

        self._wait_for_page_ready(timeout=10)
        current_url = self.driver.current_url

        if self._has_visible_error_message():
            raise RuntimeError(f"Login failed. The portal returned an explicit error message. URL: {current_url}")

        if current_url == initial_url and self._is_login_form_present():
            print("The sign-in action was sent, but the portal stayed on the login form. Waiting a bit longer...")
            time.sleep(8)
            current_url = self.driver.current_url

            if self._has_visible_error_message():
                raise RuntimeError(f"Login failed. The portal returned an explicit error message. URL: {current_url}")

            if current_url == initial_url and self._is_login_form_present():
                print(f"Portal still on the login form after submit. URL: {current_url}")
                print(f"Page title: {self.driver.title}")
                return

        print("Login command sent; waiting briefly for the portal to settle...")
        time.sleep(2)
        print("Login verified: Credentials accepted.")

    def export_status_excel(self, timeout: int = 45) -> Path:
        wait = WebDriverWait(self.driver, timeout)

        try:
            repo_menu = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.sub-menu[data-menu='Explorador'] a.prevent-dragging")))
            print("Clicking 'Repositorio'...")
            self._click_element(repo_menu)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Repositorio menu: {e}")

        try:
            explorer_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, '/AppSGD/Documentos/Carpeta/Explorador') and contains(normalize-space(.), 'Explorador')]")))
            print("Clicking 'Explorador'...")
            self._click_element(explorer_link)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Explorer link: {e}")

        self._wait_for_page_ready(timeout=10)

        try:
            filters_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(normalize-space(.), 'Filtros')]")))
            print("Clicking 'Filtros'...")
            self._click_element(filters_button)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Filtros: {e}")

        try:
            discipline_input = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.CSS_SELECTOR,
                        "input.k-input.k-readonly[aria-owns*='Disciplina_taglist'][aria-owns*='Disciplina_listbox']",
                    )
                )
            )
            print("Opening 'Disciplina' selector...")
            self._click_element(discipline_input)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Disciplina input field: {e}")

        try:
            electricity_option = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//li[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'electricidad')]",
                    )
                )
            )
            print("Selecting 'Electricidad'...")
            self._click_element(electricity_option)
        except TimeoutException as e:
            raise RuntimeError(f"Could not select Electricidad option from the list: {e}")

        try:
            buscar_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(normalize-space(.), 'Buscar')]")))
            print("Clicking 'Buscar'...")
            self._click_element(buscar_button)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Buscar button: {e}")

        self._wait_for_page_ready(timeout=10)

        try:
            export_button = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.CSS_SELECTOR,
                        "a.btn.btn-primary.bgm-green.btn-block.waves-effect",
                    )
                )
            )
            print("Clicking 'Exportar'...")
            self._click_element(export_button)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Exportar button: {e}")

        try:
            excel_option = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//ul[contains(@class, 'dropdown-menu') and contains(@class, 'dm-icon')]//a[contains(normalize-space(.), 'Excel')]",
                    )
                )
            )
            print("Selecting 'Excel'...")
            self._click_element(excel_option)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Excel option: {e}")

        print("Waiting 15 seconds for the export to complete...")
        time.sleep(15)
        return self.download_dir / "status_export.xlsx"

    def close(self) -> None:
        self.driver.quit()


def prompt_for_credentials() -> tuple[str, str]:
    username = input("Username: ").strip()
    
    while True:
        password = input("Password: ").strip()
        print(f"\nPassword entered: {password}")
        print(f"Password length: {len(password)} characters")
        confirm = input("Is this correct? (y/n): ").strip().lower()
        if confirm == "y":
            print()
            break
        else:
            print("Please try again.\n")
    
    return username, password
