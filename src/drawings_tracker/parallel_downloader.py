"""Multi-account parallel drawing downloader.

Orchestrates multiple portal accounts, each running up to N concurrent
Selenium sessions, to download drawings in parallel from a shared work queue.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AccountCredentials:
    username: str
    password: str


@dataclass(slots=True)
class DownloadResult:
    drawing_id: str
    success: bool
    error: str | None = None
    account: str = ""
    worker_id: str = ""
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Credentials loader
# ---------------------------------------------------------------------------

def load_credentials(path: str | Path) -> list[AccountCredentials]:
    """Load account credentials from a JSON file.

    Expected format::

        [
          {"username": "user@example.com", "password": "secret"},
          ...
        ]
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Credentials file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(
            "credentials.json must be a non-empty JSON array of "
            '{"username": "...", "password": "..."} objects.'
        )

    credentials: list[AccountCredentials] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {index} in credentials.json is not a JSON object.")
        username = entry.get("username", "").strip()
        password = entry.get("password", "").strip()
        if not username or not password:
            raise ValueError(
                f"Entry {index} in credentials.json is missing 'username' or 'password'."
            )
        credentials.append(AccountCredentials(username=username, password=password))

    return credentials


# ---------------------------------------------------------------------------
# Thread-safe progress reporter
# ---------------------------------------------------------------------------

class ProgressReporter:
    """Thread-safe progress tracker with live console output."""

    def __init__(self, total: int) -> None:
        self.total = total
        self._completed = 0
        self._successes = 0
        self._failures = 0
        self._lock = threading.Lock()
        self._results: list[DownloadResult] = []

    def report(self, result: DownloadResult) -> None:
        with self._lock:
            self._completed += 1
            if result.success:
                self._successes += 1
            else:
                self._failures += 1
            self._results.append(result)

            status = "OK" if result.success else f"FAILED: {result.error}"
            print(
                f"  [{self._completed}/{self.total}] "
                f"{result.drawing_id} via {result.account}/{result.worker_id} "
                f"({result.duration_seconds:.1f}s) — {status}"
            )

    def get_results(self) -> list[DownloadResult]:
        with self._lock:
            return list(self._results)

    @property
    def summary(self) -> dict[str, int]:
        with self._lock:
            return {
                "total": self.total,
                "completed": self._completed,
                "successes": self._successes,
                "failures": self._failures,
            }


# ---------------------------------------------------------------------------
# Interactive configuration helper
# ---------------------------------------------------------------------------

def configure_parallel_downloader(abort_monitor) -> tuple[list[AccountCredentials], int, bool] | None:
    """Interactively prompt the user for parallel download settings:
    - Number of accounts and their credentials
    - Number of threads per account
    - Visible vs Headless mode

    Returns (credentials_list, threads_per_account, headless) or None if cancelled.
    """
    creds_path = Path("credentials.json")
    credentials: list[AccountCredentials] = []

    if creds_path.exists():
        try:
            saved_creds = load_credentials(creds_path)
            print(f"\nFound saved credentials.json with {len(saved_creds)} account(s):")
            for c in saved_creds:
                print(f"  • {c.username}")
            
            use_saved = abort_monitor.wait_for_command(
                "\nUse these saved credentials? (Y/n): "
            ).strip().lower()
            if use_saved not in {"n", "no"}:
                credentials = saved_creds
        except Exception as e:
            print(f"Warning: Could not parse saved credentials.json ({e}).")

    if not credentials:
        print("\n--- Parallel Accounts Setup ---")
        try:
            raw_num = abort_monitor.wait_for_command(
                "How many portal accounts will you use for parallel downloading? [default: 1]: "
            ).strip()
            num_accounts = int(raw_num) if raw_num.isdigit() and int(raw_num) > 0 else 1
        except Exception:
            num_accounts = 1

        for i in range(1, num_accounts + 1):
            print(f"\n[Account {i}/{num_accounts}]")
            user = abort_monitor.wait_for_command(f"  Username for Account {i}: ").strip()
            pwd = abort_monitor.wait_for_command(f"  Password for Account {i}: ").strip()
            if user and pwd:
                credentials.append(AccountCredentials(username=user, password=pwd))
            else:
                print("  Skipped invalid account credentials.")

        if not credentials:
            print("No valid account credentials provided.")
            return None

        # Offer to save credentials
        save_choice = abort_monitor.wait_for_command(
            "\nSave these credentials to credentials.json for future runs? (y/N): "
        ).strip().lower()
        if save_choice in {"y", "yes"}:
            try:
                creds_data = [{"username": c.username, "password": c.password} for c in credentials]
                creds_path.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")
                print("Saved credentials to credentials.json.")
            except Exception as save_err:
                print(f"Could not save credentials.json: {save_err}")

    # Prompt for threads per account
    try:
        raw_threads = abort_monitor.wait_for_command(
            "\nHow many parallel threads (browser instances) per account? [default: 2]: "
        ).strip()
        threads_per_account = int(raw_threads) if raw_threads.isdigit() and int(raw_threads) > 0 else 2
    except Exception:
        threads_per_account = 2

    # Prompt for visible vs headless mode (default visible = False for headless)
    raw_mode = abort_monitor.wait_for_command(
        "Run browsers in visible window mode or headless mode? (V=Visible / h=Headless) [default: V]: "
    ).strip().lower()
    headless = (raw_mode in {"h", "headless"})

    return credentials, threads_per_account, headless


# ---------------------------------------------------------------------------
# Worker session — one Selenium driver per thread
# ---------------------------------------------------------------------------

class WorkerSession:
    """A single download worker: owns an isolated SeleniumRunner instance,
    logs in, navigates to Explorer, and processes drawing IDs from a queue."""

    def __init__(
        self,
        *,
        worker_id: str,
        credential: AccountCredentials,
        portal_url: str,
        download_dir: Path,
        work_queue: queue.Queue[str],
        reporter: ProgressReporter,
        abort_event: threading.Event,
        headless: bool = True,
    ) -> None:
        self.worker_id = worker_id
        self.credential = credential
        self.portal_url = portal_url
        self.download_dir = download_dir
        self.work_queue = work_queue
        self.reporter = reporter
        self.abort_event = abort_event
        self.headless = headless

        # Each worker gets its own temporary download directory
        self.temp_dir = download_dir / ".tmp" / worker_id
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        """Main worker loop: login, navigate, then pull IDs until the queue
        is empty or abort is requested."""
        from drawings_tracker.selenium_runner import SeleniumRunner

        runner: SeleniumRunner | None = None
        # Try session initialization up to 3 times
        max_init_attempts = 3
        initialized = False

        for attempt in range(1, max_init_attempts + 1):
            if self.abort_event.is_set():
                return
            try:
                if runner is not None:
                    try:
                        runner.close()
                    except Exception:
                        pass
                runner = SeleniumRunner(
                    download_dir=self.temp_dir, headless=self.headless
                )
                runner.login(self.portal_url, self.credential.username, self.credential.password)
                print(f"  [{self.worker_id}] Logged in as {self.credential.username}")

                runner.navigate_to_explorer()
                print(f"  [{self.worker_id}] Navigator ready on Explorer page")
                initialized = True
                break
            except Exception as init_err:
                print(f"  [{self.worker_id}] Session init attempt {attempt}/{max_init_attempts} failed: {init_err}")
                time.sleep(3.0)

        if not initialized or runner is None:
            print(f"  [{self.worker_id}] Failed to initialize after {max_init_attempts} attempts. Aborting worker.")
            return

        try:
            while not self.abort_event.is_set():
                try:
                    drawing_id = self.work_queue.get_nowait()
                except queue.Empty:
                    break  # No more work

                start = time.time()
                try:
                    runner.download_drawing(drawing_id)
                    elapsed = time.time() - start

                    # Move completed files from temp dir to final drawings dir
                    self._collect_downloaded_files(drawing_id)

                    self.reporter.report(DownloadResult(
                        drawing_id=drawing_id,
                        success=True,
                        account=self.credential.username,
                        worker_id=self.worker_id,
                        duration_seconds=elapsed,
                    ))
                except Exception as e:
                    elapsed = time.time() - start
                    self.reporter.report(DownloadResult(
                        drawing_id=drawing_id,
                        success=False,
                        error=str(e),
                        account=self.credential.username,
                        worker_id=self.worker_id,
                        duration_seconds=elapsed,
                    ))
                finally:
                    self.work_queue.task_done()

        except Exception as e:
            print(f"  [{self.worker_id}] Session error: {e}")
        finally:
            if runner is not None:
                try:
                    runner.close()
                except Exception:
                    pass

    def _collect_downloaded_files(self, drawing_id: str | None = None) -> None:
        """Move any new files from the temp directory to the appropriate category
        subfolder under ``downloads/drawings/<CATEGORY>/``."""
        from drawings_tracker.categorizer import get_category_folder

        drawings_dir = self.download_dir / "drawings"
        drawings_dir.mkdir(parents=True, exist_ok=True)

        for file in self.temp_dir.iterdir():
            if file.is_file() and not file.name.startswith("."):
                category_dir = get_category_folder(drawings_dir, drawing_id or "", file.name)
                dest = category_dir / file.name
                if dest.exists():
                    # Avoid collisions by appending worker id
                    dest = category_dir / f"{file.stem}_{self.worker_id}{file.suffix}"
                try:
                    shutil.move(str(file), str(dest))
                except Exception as move_err:
                    print(f"  [{self.worker_id}] Could not move {file.name}: {move_err}")


# ---------------------------------------------------------------------------
# Account worker pool — N threads per account
# ---------------------------------------------------------------------------

class AccountWorkerPool:
    """Manages a pool of WorkerSession threads for a single account."""

    def __init__(
        self,
        *,
        credential: AccountCredentials,
        portal_url: str,
        download_dir: Path,
        work_queue: queue.Queue[str],
        reporter: ProgressReporter,
        abort_event: threading.Event,
        threads_per_account: int = 5,
        headless: bool = True,
    ) -> None:
        self.credential = credential
        self.portal_url = portal_url
        self.download_dir = download_dir
        self.work_queue = work_queue
        self.reporter = reporter
        self.abort_event = abort_event
        self.threads_per_account = threads_per_account
        self.headless = headless
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Spawn worker threads for this account."""
        short_user = self.credential.username.split("@")[0]
        for i in range(self.threads_per_account):
            worker_id = f"{short_user}_w{i}"
            session = WorkerSession(
                worker_id=worker_id,
                credential=self.credential,
                portal_url=self.portal_url,
                download_dir=self.download_dir,
                work_queue=self.work_queue,
                reporter=self.reporter,
                abort_event=self.abort_event,
                headless=self.headless,
            )
            thread = threading.Thread(
                target=session.run, name=f"worker-{worker_id}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

            # Stagger launches slightly to avoid simultaneous login storms
            time.sleep(3.0)

    def join(self, timeout: float | None = None) -> None:
        """Wait for all worker threads to finish."""
        for thread in self._threads:
            thread.join(timeout=timeout)


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

class ParallelDownloader:
    """Orchestrates multi-account parallel downloads.

    Usage::

        downloader = ParallelDownloader(
            drawing_ids=["ABC-001", "ABC-002", ...],
            credentials=load_credentials("credentials.json"),
            download_dir=Path("downloads"),
        )
        results = downloader.run()
        downloader.print_summary(results)
    """

    def __init__(
        self,
        *,
        drawing_ids: list[str],
        credentials: list[AccountCredentials],
        download_dir: Path,
        portal_url: str = "https://sgc.cumbra.com.pe/AppMSSO/",
        threads_per_account: int = 5,
        headless: bool = True,
        abort_event: threading.Event | None = None,
    ) -> None:
        self.drawing_ids = drawing_ids
        self.credentials = credentials
        self.download_dir = Path(download_dir).resolve()
        self.portal_url = portal_url
        self.threads_per_account = threads_per_account
        self.headless = headless
        self.abort_event = abort_event or threading.Event()

    def run(self) -> list[DownloadResult]:
        """Execute parallel downloads and return results."""
        total = len(self.drawing_ids)
        total_threads = len(self.credentials) * self.threads_per_account

        print(f"\n{'=' * 50}")
        print(f"  PARALLEL DOWNLOAD — {total} drawings")
        print(f"  Accounts: {len(self.credentials)}  |  "
              f"Threads/account: {self.threads_per_account}  |  "
              f"Total threads: {total_threads}")
        print(f"{'=' * 50}\n")

        # Build shared work queue
        work_queue: queue.Queue[str] = queue.Queue()
        for drawing_id in self.drawing_ids:
            work_queue.put(drawing_id)

        reporter = ProgressReporter(total)

        # Create and start one pool per account
        pools: list[AccountWorkerPool] = []
        for credential in self.credentials:
            pool = AccountWorkerPool(
                credential=credential,
                portal_url=self.portal_url,
                download_dir=self.download_dir,
                work_queue=work_queue,
                reporter=reporter,
                abort_event=self.abort_event,
                threads_per_account=self.threads_per_account,
                headless=self.headless,
            )
            pool.start()
            pools.append(pool)

        # Wait for all work to complete
        for pool in pools:
            pool.join()

        # Cleanup temp directories
        tmp_root = self.download_dir / ".tmp"
        if tmp_root.exists():
            try:
                shutil.rmtree(tmp_root)
            except Exception:
                pass

        return reporter.get_results()

    @staticmethod
    def print_summary(results: list[DownloadResult]) -> None:
        """Print a final summary table of all download results."""
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]

        print(f"\n{'=' * 50}")
        print(f"  DOWNLOAD SUMMARY")
        print(f"{'=' * 50}")
        print(f"  Total:     {len(results)}")
        print(f"  Success:   {len(successes)}")
        print(f"  Failed:    {len(failures)}")

        if successes:
            avg_time = sum(r.duration_seconds for r in successes) / len(successes)
            total_time = sum(r.duration_seconds for r in successes)
            print(f"  Avg time:  {avg_time:.1f}s per drawing")
            print(f"  Total time: {total_time:.1f}s (wall clock is less due to parallelism)")

        if failures:
            print(f"\n  FAILED DOWNLOADS:")
            for r in failures:
                print(f"    • {r.drawing_id}: {r.error}")

        print(f"{'=' * 50}\n")
