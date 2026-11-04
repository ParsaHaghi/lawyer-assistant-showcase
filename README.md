# Smart Lawyer Assistant

**Smart Lawyer Assistant** is a comprehensive document and automation management system tailored specifically for Iranian lawyers. It automates interaction with the Sana (Adliran) portal and manages client documents securely and efficiently.

---

## 🌟 Features

- **Automated Workflow**: Integrates seamlessly with Sana (Adliran) for downloading and filing documents.
- **Intelligent PDF Parsing**: Extracts client data (National ID, Contract Number, Case Number) directly from legal PDFs using PyPDF2.
- **Client Management**: Organizes files into client-specific folders and manages document status automatically.
- **Modern UI & API**: Powered by FastAPI backend and an easy-to-use graphical launcher.
- **Robust Automation**: Utilizes Playwright for headless and headed browser automation.
- **Optimized & Clean Codebase**: Fully PEP8 compliant and optimized for Python 3.14 features.

---

## 📂 Project Structure

```text
Lawyer_Assistant/
│
├── automation/                 # Playwright automation scripts for Sana
│   ├── __init__.py
│   ├── base.py                 # Core automation logic & login
│   ├── electronic_contract.py  # Contract processing
│   └── initial_document.py     # Initial document handling
│
├── clients/                    # Auto-generated directory for client files
├── static/                     # Frontend static assets (CSS, JS, Images)
│
├── config.json                 # Main workspace configuration
├── sana_config.json            # Sana login credentials
│
├── gui_app.py                  # Graphical launcher & dependency checker
├── web_app.py                  # FastAPI server & backend logic
├── pdf_reader.py               # Legacy / Basic PDF extraction
├── pdf_reader2.py              # Advanced PDF parsing & Regex
├── migrate_folders.py          # Utility for folder migration
│
└── requirements.txt            # Python dependencies list
```

---

## 🚀 Installation & Usage

### Prerequisites
- Python 3.10+ (Recommended Python 3.14+)
- Google Chrome or Chromium

### 1. Setup Environment
Install dependencies via pip:
```bash
pip install -r requirements.txt
playwright install chromium
```
*Note: If using `gui_app.py`, it will automatically install missing dependencies.*

### 2. Run the Application
You can start the assistant using the GUI launcher:
```bash
python gui_app.py
```
This will start the FastAPI backend on `http://127.0.0.1:8001` and open the dashboard in your default browser.

---

## ⚙️ Configuration

- **`config.json`**: Manages the `workspace_path` (default is `./clients`). 
- **`sana_config.json`**: Holds your Sana login details.
  ```json
  {
    "national_code": "YOUR_CODE",
    "password": "YOUR_PASSWORD"
  }
  ```

