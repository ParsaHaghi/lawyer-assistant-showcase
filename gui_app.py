"""
دستیار وکیل هوشمند - راه‌انداز برنامه تحت وب
"""

import sys
import os
import subprocess
import threading
import time
import webbrowser


# Function to install dependencies if they are missing
def install_dependencies():
    print("\n[+] Checking and installing missing dependencies...")
    requirements_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "requirements.txt"
    )
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", requirements_path],
            check=True,
        )
        print("[+] Installing Playwright browsers...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"], check=True
        )
        print("[+] Dependencies installed successfully!\n")
    except Exception as e:
        print(f"[-] Error installing dependencies: {e}")
        print("[-] Please run 'pip install -r requirements.txt' manually.")
        sys.exit(1)


# Check and import dependencies
try:
    import fastapi
    import uvicorn
    import PyPDF2
    import playwright
except ImportError:
    install_dependencies()
    # Re-import after installation
    import uvicorn


def open_browser():
    """Wait for server startup and open the browser"""
    time.sleep(1.5)
    url = "http://127.0.0.1:8001"
    print(f"\n[+] Opening browser at {url} ...")
    webbrowser.open(url)


def main():
    print("=" * 60)
    print("       Smart Lawyer Assistant - Document Management System")
    print("=" * 60)
    print("[+] Starting backend server...")

    # Start browser opener in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start FastAPI backend server using uvicorn
    try:
        uvicorn.run(
            "web_app:app", host="127.0.0.1", port=8001, reload=False, log_level="info"
        )
    except KeyboardInterrupt:
        print("\n[+] Server stopped by user.")
    except Exception as e:
        print(f"\n[-] Error running server: {e}")


if __name__ == "__main__":
    main()
