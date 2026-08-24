from __future__ import annotations

import queue
import threading

from drawings_tracker.selenium_runner import SeleniumRunner, prompt_for_credentials


class AbortRequested(Exception):
    """Raised when the user requests cancellation from the terminal."""


class AbortMonitor:
    def __init__(self, on_abort) -> None:
        self._on_abort = on_abort
        self._aborted = threading.Event()
        self._commands: queue.Queue[str] = queue.Queue()

    @property
    def aborted(self) -> bool:
        return self._aborted.is_set()

    def start(self) -> None:
        threading.Thread(target=self._listen, daemon=True).start()
        print("\nAbort control active: type ABORT and press Enter at any time.\n")

    def _listen(self) -> None:
        while not self.aborted:
            try:
                command = input().strip()
            except (EOFError, KeyboardInterrupt):
                return
            if command.upper() in {"ABORT", "EXIT", "STOP"}:
                self._aborted.set()
                print("\nAbort requested. Stopping the browser and workflow...")
                try:
                    self._on_abort()
                except Exception:
                    pass
                return
            self._commands.put(command)

    def check(self) -> None:
        if self.aborted:
            raise AbortRequested

    def wait_for_command(self, prompt: str) -> str:
        print(prompt, end="", flush=True)
        while True:
            self.check()
            try:
                return self._commands.get(timeout=0.1)
            except queue.Empty:
                continue


def _sequential_download(change_types: dict, runner, abort_monitor) -> None:
    """Original sequential download loop — one drawing at a time with
    interactive confirmation prompts."""
    print(f"\nStarting individual drawing downloads ({len(change_types)} files)...")
    for i, drawing_id in enumerate(change_types.keys(), 1):
        user_input = abort_monitor.wait_for_command(
            f"\n[{i}/{len(change_types)}] Ready to download drawing: "
            f"'{drawing_id}'. Press Enter to proceed (or type 'skip' "
            "to skip, 'ABORT' to stop): "
        ).strip().lower()
        if user_input == "skip":
            print(f"Skipping download for '{drawing_id}'.")
            continue
        try:
            abort_monitor.check()
            runner.download_drawing(drawing_id)
            abort_monitor.check()
        except Exception as download_err:
            abort_monitor.check()
            print(f"Error downloading '{drawing_id}': {download_err}")


def main() -> None:
    url = "https://sgc.cumbra.com.pe/AppMSSO/"
    from pathlib import Path
    downloads_dir = Path("downloads").resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Locate the existing previous export file BEFORE we download the new one
    existing_exports = sorted(
        [f for f in downloads_dir.glob("status_export_*.xlsx") if f.is_file()],
        key=lambda p: p.stat().st_mtime
    )

    # A normal run compares one existing baseline with one newly downloaded
    # export. If multiple baselines already exist, require an explicit command
    # instead of silently choosing one from an ambiguous set.
    if len(existing_exports) > 1:
        print("\a")
        print("!" * 70)
        print("ALERT: MORE THAN TWO STATUS EXPORTS WOULD BE INVOLVED")
        print("The following previous export files were found:")
        for export_file in existing_exports:
            print(f"  - {export_file.name}")
        print("\nThe workflow has been paused before login or downloading.")
        confirmation = input(
            "Type CONTINUE to use the newest file as the baseline, "
            "or press Enter to stop: "
        ).strip()
        if confirmation != "CONTINUE":
            print("Stopped. No portal actions or comparisons were performed.")
            return
        print("Explicit CONTINUE command received. Resuming workflow.\n")

    previous_path = existing_exports[-1] if existing_exports else None
    
    if previous_path:
        print(f"Pre-located previous baseline file for comparison: {previous_path.name}")
    else:
        print("No previous export file found in downloads/ to compare against.")

    username, password = prompt_for_credentials()
    runner = SeleniumRunner(download_dir=downloads_dir, headless=False)
    close_lock = threading.Lock()
    browser_closed = False

    def close_browser() -> None:
        nonlocal browser_closed
        with close_lock:
            if browser_closed:
                return
            browser_closed = True
            runner.request_abort()
            runner.close()

    abort_monitor = AbortMonitor(close_browser)
    abort_monitor.start()
    try:
        abort_monitor.check()
        runner.login(url, username, password)
        abort_monitor.check()
        print("Login verified successfully. Proceeding through the repository flow...")
        export_path = runner.export_status_excel()
        abort_monitor.check()
        print(f"Export step completed. File saved at: {export_path.name}")
        
        if previous_path:
            print(f"\nComparing {export_path.name} against previous baseline: {previous_path.name}")
            
            from drawings_tracker.core import DrawingTracker
            tracker = DrawingTracker()
            changes = tracker.compare_status_files(previous_path, export_path)
            abort_monitor.check()
            
            # Print the comparison results
            print(f"\n==========================================")
            print(f"           COMPARISON SUMMARY")
            print(f"==========================================")
            print(f"New Drawings Added: {len(changes['new_drawings'])}")
            print(f"Updated Drawings:   {len(changes['updated_drawings'])}")
            print(f"==========================================")
            
            if changes["new_drawings"]:
                print("\n[+] NEW DRAWINGS:")
                for item in changes["new_drawings"]:
                    print(f"  • Tag/ID: {item['drawing_id']}")
                    print(f"    Revision: {item.get('revision', 'N/A')} | Status: {item.get('status', 'N/A')}")
            
            if changes["updated_drawings"]:
                print("\n[*] REVISION / STATUS CHANGES:")
                for item in changes["updated_drawings"]:
                    print(f"  • Tag/ID: {item['drawing_id']}")
                    if item.get("previous_revision") != item.get("latest_revision"):
                        print(f"    Revision Change: {item.get('previous_revision', 'N/A')} ➔ {item.get('latest_revision', 'N/A')}")
                    if item.get("previous_status") != item.get("latest_status"):
                        print(f"    Status Change:   {item.get('previous_status', 'N/A')} ➔ {item.get('latest_status', 'N/A')}")
            
            # Map each changed drawing ID to its change type (NEW or UPDATED)
            change_types = {}
            skipped_missing_ids = 0
            for item in changes["new_drawings"]:
                raw_drawing_id = item.get("drawing_id")
                drawing_id = "" if raw_drawing_id is None else str(raw_drawing_id).strip()
                if not drawing_id or drawing_id.lower() in {"nan", "none", "nat"}:
                    skipped_missing_ids += 1
                    continue
                change_types[drawing_id] = "NEW"
            for item in changes["updated_drawings"]:
                raw_drawing_id = item.get("drawing_id")
                drawing_id = "" if raw_drawing_id is None else str(raw_drawing_id).strip()
                if not drawing_id or drawing_id.lower() in {"nan", "none", "nat"}:
                    skipped_missing_ids += 1
                    continue
                change_types[drawing_id] = "UPDATED"

            if skipped_missing_ids:
                print(
                    f"Warning: skipped {skipped_missing_ids} changed row(s) "
                    "because the drawing ID was missing."
                )

            if change_types:
                abort_monitor.check()
                import pandas as pd
                latest_df = pd.read_excel(export_path)
                
                from drawings_tracker.core import DrawingTracker
                tracker_helper = DrawingTracker()
                drawing_column = tracker_helper._find_column(latest_df, "drawing_id", "drawing", "drawing_no", "drawingnumber", "codigo")
                
                if drawing_column:
                    # Filter rows where drawing ID is in the changed IDs
                    latest_df_copy = latest_df.copy()
                    latest_df_copy[drawing_column] = latest_df_copy[drawing_column].astype(str).str.strip()
                    filtered_df = latest_df[latest_df_copy[drawing_column].isin(change_types.keys())].copy()
                    
                    # Add the Change Type column as the first column in the CSV
                    filtered_df.insert(0, "Change Type", filtered_df[drawing_column].map(change_types))
                    
                    # Extract timestamp from export_path filename to keep the same format
                    stem = export_path.stem
                    if "_" in stem:
                        parts = stem.split("_")
                        timestamp = f"{parts[-2]}_{parts[-1]}"
                    else:
                        import datetime
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    csv_filename = downloads_dir / f"changes_{timestamp}.csv"
                    abort_monitor.check()
                    filtered_df.to_csv(csv_filename, index=False, encoding="utf-8-sig")
                    print(f"Comparison details saved to CSV: {csv_filename.name}")
                else:
                    print("Error: Could not identify Drawing ID / Código column in the Excel file to generate the filtered CSV.")
            else:
                print("No changes detected. CSV file was not created.")

            # Download the changed drawings
            if change_types:
                # Try parallel download if credentials.json exists
                creds_path = Path("credentials.json")
                if creds_path.exists():
                    from drawings_tracker.parallel_downloader import (
                        load_credentials,
                        ParallelDownloader,
                    )
                    try:
                        credentials = load_credentials(creds_path)
                    except Exception as creds_err:
                        print(f"Error loading credentials.json: {creds_err}")
                        print("Falling back to sequential downloads.")
                        credentials = None

                    if credentials:
                        drawing_list = list(change_types.keys())
                        print(
                            f"\nParallel download mode: {len(drawing_list)} drawings "
                            f"across {len(credentials)} account(s)."
                        )
                        confirmation = abort_monitor.wait_for_command(
                            "Press Enter to start parallel downloads "
                            "(or type ABORT to cancel): "
                        ).strip().lower()
                        if confirmation not in {"abort", "stop", "exit"}:
                            abort_monitor.check()
                            # Close the single-account browser; parallel workers
                            # create their own isolated sessions.
                            close_browser()
                            downloader = ParallelDownloader(
                                drawing_ids=drawing_list,
                                credentials=credentials,
                                download_dir=downloads_dir,
                                threads_per_account=5,
                                headless=True,
                                abort_event=abort_monitor._aborted,
                            )
                            results = downloader.run()
                            downloader.print_summary(results)
                        else:
                            print("Parallel downloads cancelled by user.")
                    else:
                        # credentials failed to load — fall through to sequential
                        _sequential_download(
                            change_types, runner, abort_monitor
                        )
                else:
                    # No credentials.json — original sequential behaviour
                    _sequential_download(change_types, runner, abort_monitor)
                
            print(f"==========================================\n")
        else:
            print("\nSkipping comparison because no previous export file existed before this run.")
            
    except AbortRequested:
        print("Workflow aborted by user. No further actions will be performed.")
        return
    except Exception as e:
        if abort_monitor.aborted:
            print("Workflow aborted by user. No further actions will be performed.")
            return
        print(f"Error: {e}")
        return
    finally:
        try:
            close_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
