from __future__ import annotations

from drawings_tracker.selenium_runner import SeleniumRunner, prompt_for_credentials


def main() -> None:
    url = "https://sgc.cumbra.com.pe/AppMSSO/"
    username, password = prompt_for_credentials()
    runner = SeleniumRunner(download_dir="downloads", headless=False)
    try:
        runner.login(url, username, password)
        print("Login verified successfully. Proceeding through the repository flow...")
        export_path = runner.export_status_excel()
        print(f"Export step attempted. File expected at: {export_path}")
    except RuntimeError as e:
        print(f"Error: {e}")
        return
    finally:
        runner.close()


if __name__ == "__main__":
    main()
