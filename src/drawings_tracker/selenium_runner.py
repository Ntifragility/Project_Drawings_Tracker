from __future__ import annotations

import json
import re
import time
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class SeleniumRunner:
    def __init__(self, download_dir: str | Path, headless: bool = True) -> None:
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._abort_requested = threading.Event()
        self.driver = self._build_driver(headless=headless)

    def request_abort(self) -> None:
        self._abort_requested.set()

    def _check_abort(self) -> None:
        if self._abort_requested.is_set():
            raise RuntimeError("Workflow aborted by user.")

    def _capture_diagnostic(self, stage: str) -> None:
        """Save local browser evidence without interrupting the workflow."""
        try:
            diagnostics_dir = Path("diagnostics").resolve()
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage).strip("_")
            stem = diagnostics_dir / f"{timestamp}_{safe_stage}"

            page_html = self.driver.page_source
            page_html = re.sub(
                r'(<input[^>]*type=["\']password["\'][^>]*value=)["\'][^"\']*["\']',
                r'\1"[REDACTED]"',
                page_html,
                flags=re.IGNORECASE,
            )
            stem.with_suffix(".html").write_text(page_html, encoding="utf-8")
            self.driver.save_screenshot(str(stem.with_suffix(".png")))

            current_url = urlsplit(self.driver.current_url)
            safe_url = urlunsplit(
                (current_url.scheme, current_url.netloc, current_url.path, "", "")
            )
            download_links = []
            for link in self.driver.find_elements(
                By.XPATH, "//a[contains(@onclick, 'descargarArchivo(')]"
            ):
                download_links.append(
                    {
                        "displayed": link.is_displayed(),
                        "enabled": link.is_enabled(),
                        "text": link.text.strip(),
                        "onclick": link.get_attribute("onclick"),
                        "class": link.get_attribute("class"),
                    }
                )
            frames = [
                {
                    "id": frame.get_attribute("id"),
                    "name": frame.get_attribute("name"),
                    "src": frame.get_attribute("src"),
                }
                for frame in self.driver.find_elements(By.TAG_NAME, "iframe")
            ]
            metadata = {
                "stage": stage,
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "url_without_query": safe_url,
                "title": self.driver.title,
                "download_links": download_links,
                "iframes": frames,
            }
            stem.with_suffix(".json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"Diagnostic captured: diagnostics/{stem.name}.*")
        except Exception as diagnostic_error:
            print(f"Could not capture diagnostic for '{stage}': {diagnostic_error}")

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
        try:
            body_element = self.driver.find_element(By.TAG_NAME, "body")
            if body_element.is_displayed():
                body_text = body_element.text.lower()
                if any(keyword in body_text for keyword in keywords):
                    return True
        except Exception:
            pass
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

    def _ensure_filtros_unfolded(self, timeout: int = 15) -> None:
        wait = WebDriverWait(self.driver, timeout)
        try:
            toggle_anchor = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@onclick, 'filtroToogle')]")))
            folded_indicator = toggle_anchor.find_element(By.XPATH, ".//span[contains(@class, 'toggleButton') and .//i[contains(@class, 'zmdi-chevron-down')]]")
            
            style_attr = folded_indicator.get_attribute("style") or ""
            if "display: none" not in style_attr:
                print("Filtros section is folded. Clicking toggle button to unfold...")
                self._click_element(toggle_anchor)
                time.sleep(1.0)
            else:
                print("Filtros section is already unfolded.")
        except Exception as e:
            print(f"Warning: Could not determine Filtros unfold status via toggle buttons ({e}). Trying fallback check...")
            try:
                search_input = self.driver.find_element(By.ID, "Codigo")
                if not search_input.is_displayed():
                    filters_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@onclick, 'filtroToogle')]")))
                    self._click_element(filters_button)
                    time.sleep(1.0)
            except Exception as fallback_err:
                print(f"Warning: Fallback Filtros unfold failed: {fallback_err}")

    def login(self, url: str, username: str, password: str) -> None:
        self.driver.get(url)
        wait = WebDriverWait(self.driver, 20)

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

        # Wait for the login redirection to complete by checking the DOM for the main page sidebar or error indicators
        print("Verifying login redirection...")
        try:
            WebDriverWait(self.driver, 20).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "#menu-trigger") or self._has_visible_error_message()
            )
        except TimeoutException:
            pass

        current_url = self.driver.current_url
        if self._has_visible_error_message():
            raise RuntimeError(f"Login failed. The portal returned an explicit error message. URL: {current_url}")

        if self._is_login_form_present():
            raise RuntimeError(f"Login failed. Still on login page. URL: {current_url}")

        print("Login verified: Credentials accepted.")

    def navigate_to_explorer(self, timeout: int = 45) -> None:
        """Navigate to the Explorer page, select ELECTRICA discipline, and
        load the grid so that the search interface is ready for use."""
        wait = WebDriverWait(self.driver, timeout)

        try:
            repo_menu = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.sub-menu[data-menu='Explorador'] a.prevent-dragging")))
            print("Clicking 'Repositorio'...")
            self._click_element(repo_menu)
        except TimeoutException as e:
            try:
                print("Sidebar menu might be folded. Clicking menu-trigger to unfold...")
                menu_trigger = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#menu-trigger")))
                self._click_element(menu_trigger)
                repo_menu = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.sub-menu[data-menu='Explorador'] a.prevent-dragging")))
                print("Clicking 'Repositorio'...")
                self._click_element(repo_menu)
            except Exception as trigger_err:
                raise RuntimeError(f"Could not click Repositorio menu even after attempting to toggle sidebar: {e}; trigger error: {trigger_err}")

        try:
            explorer_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, '/AppSGD/Documentos/Carpeta/Explorador') and contains(normalize-space(.), 'Explorador')]")))
            print("Clicking 'Explorador'...")
            self._click_element(explorer_link)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Explorer link: {e}")

        self._wait_for_page_ready(timeout=10)

        self._ensure_filtros_unfolded(timeout=timeout)

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
            listbox = wait.until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(@id, 'Disciplina_listbox')]"))
            )
            wait.until(
                lambda d: len(listbox.find_elements(By.TAG_NAME, "li")) > 0
            )
        except TimeoutException as e:
            raise RuntimeError(f"Dropdown list did not populate in time: {e}")

        try:
            def click_electricity(d):
                try:
                    el = d.find_element(
                        By.XPATH,
                        "//li[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'electrica')]",
                    )
                    if el.is_displayed() and el.is_enabled():
                        self._click_element(el)
                        return True
                except (StaleElementReferenceException, NoSuchElementException):
                    pass
                return False

            print("Selecting 'ELECTRICA'...")
            wait.until(click_electricity)
        except TimeoutException as e:
            raise RuntimeError(f"Could not locate or click ELECTRICA option: {e}")

        try:
            buscar_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(normalize-space(.), 'Buscar')]")))
            print("Clicking 'Buscar'...")
            self._click_element(buscar_button)
        except TimeoutException as e:
            raise RuntimeError(f"Could not click Buscar button: {e}")

        self._wait_for_page_ready(timeout=10)
        
        try:
            WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".k-loading-mask, .loading-mask, .k-loading-image, .loading, .spinner"))
            )
        except TimeoutException:
            pass

        try:
            WebDriverWait(self.driver, 60).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".k-loading-mask, .loading-mask, .k-loading-image, .loading, .spinner"))
            )
        except TimeoutException as e:
            raise RuntimeError(f"Page loading mask did not disappear: {e}")

        print("Waiting for grid rows to render in DOM...")
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, ".k-grid-content tbody tr, table tbody tr, .grid-row")) > 0
            )
        except TimeoutException as e:
            raise RuntimeError(f"Grid data rows did not render in the DOM: {e}")

    def export_status_excel(self, timeout: int = 45) -> Path:
        self.navigate_to_explorer(timeout=timeout)
        wait = WebDriverWait(self.driver, timeout)

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

        print("Waiting for the export to complete...")
        existing_files = set(self.download_dir.iterdir())
        
        downloaded_file = None
        timeout_time = time.time() + 60
        while time.time() < timeout_time:
            current_files = set(self.download_dir.iterdir())
            new_files = current_files - existing_files
            completed_files = [
                f for f in new_files
                if f.is_file() and not f.name.endswith(".crdownload") and not f.name.endswith(".tmp")
            ]
            if completed_files:
                downloaded_file = max(completed_files, key=lambda p: p.stat().st_mtime)
                break
            time.sleep(1)

        if not downloaded_file:
            for f in self.download_dir.glob("*.xlsx"):
                if f not in existing_files:
                    downloaded_file = f
                    break

        if downloaded_file:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_path = self.download_dir / f"status_export_{timestamp}.xlsx"
            if target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass
            try:
                downloaded_file.rename(target_path)
                print(f"File downloaded and saved as: {target_path.name}")
                return target_path
            except Exception as e:
                print(f"Could not rename downloaded file to {target_path.name}: {e}")
                return downloaded_file

        raise RuntimeError("Download timed out or failed to complete.")

    def _wait_and_move_new_file(self, existing_files: set[Path], timeout: int = 30) -> bool:
        downloaded = False
        timeout_time = time.time() + timeout
        while time.time() < timeout_time:
            self._check_abort()
            current_files = set(self.download_dir.iterdir())
            new_files = current_files - existing_files
            completed_files = [
                f for f in new_files
                if f.is_file() and not f.name.endswith(".crdownload") and not f.name.endswith(".tmp")
            ]
            if completed_files:
                downloaded = True
                new_file = max(completed_files, key=lambda p: p.stat().st_mtime)
                print(f"Successfully downloaded file: {new_file.name}")
                
                # Move the file to drawings directory
                drawings_dir = Path("drawings").resolve()
                drawings_dir.mkdir(parents=True, exist_ok=True)
                dest_file = drawings_dir / new_file.name
                try:
                    if dest_file.exists():
                        dest_file.unlink()
                    new_file.rename(dest_file)
                    print(f"Moved drawing file to: drawings/{new_file.name}")
                except Exception as move_err:
                    print(f"Could not move file to drawings folder: {move_err}")
                break
            time.sleep(1)

        if not downloaded:
            print("Warning: New download not detected in 30 seconds.")
        return downloaded

    def download_drawing(self, drawing_id: str, timeout: int = 30) -> None:
        drawing_id = "" if drawing_id is None else str(drawing_id).strip()
        if not drawing_id or drawing_id.lower() in {"nan", "none", "nat"}:
            raise ValueError("Cannot download a drawing without a valid drawing ID.")

        wait = WebDriverWait(self.driver, timeout)

        self._ensure_filtros_unfolded(timeout=timeout)

        # 1. Locate search input, enter drawing tag, and click Buscar button
        try:
            search_input = wait.until(EC.element_to_be_clickable((By.ID, "Codigo")))
            search_input.clear()
            search_input.send_keys(drawing_id)
            print(f"Pasted drawing tag: '{drawing_id}' into search field...")
            
            buscar_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'buscarClick') or contains(@class, 'bgm-orange')]")))
            self._click_element(buscar_btn)
            print("Clicked search 'Buscar' button...")
        except TimeoutException as e:
            raise RuntimeError(f"Could not locate search elements: {e}")

        # 2. Wait for dynamic content reload (loading masks to disappear)
        try:
            time.sleep(1.5)
            WebDriverWait(self.driver, 15).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".k-loading-mask, .loading-mask, .k-loading-image, .loading, .spinner"))
            )
        except TimeoutException:
            pass

        # === DOWNLOAD FILE 1 (Main Drawing) ===
        # 3. Click the dropdown button to expand actions
        try:
            btn_expanded = wait.until(EC.element_to_be_clickable((By.ID, "btnExpaded")))
            self._click_element(btn_expanded)
        except TimeoutException as e:
            raise RuntimeError(f"Could not find or click expanded button 'btnExpaded': {e}")

        # 4. Click 'Descargar' option
        try:
            download_link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.descarga a")))
            existing_files = set(self.download_dir.iterdir())
            self._click_element(download_link)
            print("Clicking main drawing 'Descargar'...")
        except TimeoutException as e:
            raise RuntimeError(f"Could not find or click main 'Descargar' link: {e}")

        # Wait for first download completion and move to drawings folder
        self._wait_and_move_new_file(existing_files)

        # === DOWNLOAD FILE 2 (Adicionales) ===
        try:
            # 1. Click Expand icon in the hierarchy cell
            print("Clicking master row expand button...")
            expand_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "tr.k-master-row td.k-hierarchy-cell a.k-i-expand")))
            self._click_element(expand_btn)
            time.sleep(1.5) # Wait briefly for tabstrip to render
            self._capture_diagnostic(f"{drawing_id}_details_expanded")

            # 2. Click on "Adicionales" tab link
            print("Clicking 'Adicionales' tab link...")
            adicionales_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@class, 'k-link') and contains(normalize-space(.), 'Adicionales')]")))
            self._click_element(adicionales_tab)
            time.sleep(1.0) # Wait briefly for additional files list to show
            self._capture_diagnostic(f"{drawing_id}_adicionales_open")

            # 3. Click download icon inside Adicionales tab
            print("Clicking additional file 'Descargar' (Adicionales)...")

            # The additional file is rendered in a Bootstrap ``col-md-6`` block
            # inside the active Kendo tab.  Target that file block directly;
            # checking the child div's inline style was too broad and could match
            # unrelated/hidden download links elsewhere on the page.
            additional_download_xpath = (
                "//div[contains(@class, 'k-content') and "
                "(contains(@class, 'k-state-active') or not(contains(@style, 'display: none')))]"
                "//div[contains(concat(' ', normalize-space(@class), ' '), ' col-md-6 ')]"
                "//a[contains(@onclick, 'descargarArchivo(') "
                "and .//i[contains(@class, 'zmdi-cloud-download')]]"
            )

            def visible_additional_downloads(driver):
                links = driver.find_elements(By.XPATH, additional_download_xpath)
                visible_links = [link for link in links if link.is_displayed() and link.is_enabled()]
                return visible_links or False

            additional_links = wait.until(visible_additional_downloads)
            additional_count = len(additional_links)
            print(f"Found {additional_count} additional file(s) to download.")

            for index in range(additional_count):
                self._check_abort()
                # Re-read the elements before each click in case the page updates
                # the tab contents after a download and invalidates old elements.
                current_links = wait.until(visible_additional_downloads)
                if index >= len(current_links):
                    print(
                        "The Adicionales file list changed while downloading; "
                        f"could not access item {index + 1}."
                    )
                    continue

                existing_files_2 = set(self.download_dir.iterdir())
                print(
                    f"Downloading additional file {index + 1} "
                    f"of {additional_count}..."
                )
                self._click_element(current_links[index])
                self._wait_and_move_new_file(existing_files_2)
            
        except Exception as e:
            self._capture_diagnostic(f"{drawing_id}_adicionales_failure")
            print(f"No additional file downloaded or failed to download Adicionales: {e}")

    def close(self) -> None:
        self.driver.quit()


def prompt_for_credentials() -> tuple[str, str]:
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    return username, password
