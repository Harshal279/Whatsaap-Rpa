# WhatsApp RPA Automator

A modern, production-ready **Robotic Process Automation** desktop application that automates WhatsApp Web messaging from an Excel contacts file.

---

## Features

| Feature | Details |
|---------|---------|
| Excel Import | Read Name / Phone / Message from `.xlsx` files |
| Multi-Browser | Chrome, Edge, Brave with persistent profiles |
| Auto-Login | QR code scan on first run; stays logged in after |
| Auto-Send | Sends messages to all contacts sequentially |
| Attachments | Send images or documents with optional captions |
| Pause / Resume | Pause mid-run and resume without restarting |
| Retry | Configurable retry on failed deliveries |
| Anti-Spam | Random delay between messages |
| Dedup | Detects and removes duplicate phone numbers |
| Reports | Auto-saves CSV & TXT delivery report per session |
| Dark UI | Premium dark-mode CustomTkinter interface |
| Threading | Background automation — UI never freezes |

---

## Project Structure

```
whatsapp_rpa/
├── main.py                   # Entry point
├── config.py                 # All constants & theme colours
├── setup.py                  # One-click environment setup
├── requirements.txt
├── create_sample_excel.py    # Generates sample_contacts.xlsx
├── sample_contacts.xlsx      # Sample data (after running setup)
│
├── core/
│   ├── browser_manager.py    # Chrome / Edge / Brave driver factory
│   ├── whatsapp_bot.py       # WhatsApp Web selenium automation
│   └── automation_engine.py  # Orchestration & threading
│
├── ui/
│   ├── main_window.py        # Main application window
│   └── widgets.py            # Reusable UI components
│
├── utils/
│   ├── logger.py             # Rotating file + UI streaming logger
│   ├── excel_reader.py       # Excel parsing & validation
│   └── report_writer.py      # CSV & TXT delivery reports
│
├── logs/                     # Runtime log files (auto-created)
├── reports/                  # Delivery reports (auto-created)
├── assets/                   # Icons / images
└── browser_profiles/         # Persistent browser session storage
```

---

## Quick Start

### Option A — Automated Setup (Recommended)

```bash
cd whatsapp_rpa
python setup.py
```

This creates a `venv`, installs all packages, and generates the sample Excel file.

Then run the app:
```bash
venv\Scripts\python main.py
```

### Option B — Manual Setup

```bash
cd whatsapp_rpa

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Generate sample Excel
python create_sample_excel.py

# Run the app
python main.py
```

---

## 📊 Excel File Format

Create an Excel file (`.xlsx`) with these **exact column names**:

| Name | Phone | Message |
|------|-------|---------|
| Rahul Sharma | 919876543210 | Hello Rahul! |
| Aman Verma | 919812345678 | Your order is ready |

> **Phone format:** Country code + number, digits only. E.g., `919876543210` for India.

---

## How to Use

1. **Run** `python main.py`
2. **Browse** and select your Excel file → contacts are loaded instantly
3. **Select** your preferred browser (Chrome / Edge / Brave)
4. **Adjust** delay range and retry count as needed
5. **Optionally** attach a file (image/document)
6. Click **Start Automation**
7. A browser window opens → **scan the QR code** (first time only)
8. Messages are sent automatically — monitor in the Live Console tab
9. When done, the delivery report is auto-saved to `reports/`

---

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Delay Min | 3 s | Minimum random delay between messages |
| Delay Max | 7 s | Maximum random delay between messages |
| Retry Count | 2 | How many times to retry a failed send |
| Remove Duplicates | On | Skip contacts with identical phone numbers |

---

## Reports

After each run, two files are saved to the `reports/` folder:
- `report_YYYYMMDD_HHMMSS.csv` — Machine-readable delivery report
- `report_YYYYMMDD_HHMMSS.txt` — Human-readable summary

Click **Export Last Report** in the UI to open the reports folder.

---

## Important Notes

- **WhatsApp Business Policy:** Use responsibly and comply with WhatsApp's Terms of Service. This tool is for legitimate business communication only.
- **Phone Number Format:** Always include the country code (e.g., `91` for India).
- **Browser Profile:** After the first QR scan, WhatsApp stays logged in via the saved browser profile in `browser_profiles/`.
- **Internet:** A stable internet connection is required throughout the automation run.

---

## Troubleshooting

| Problem | Solution |
|---------|---------|
| ChromeDriver not found | Run `pip install --upgrade webdriver-manager` |
| Brave not detected | Add the full path to `BRAVE_PATHS` in `config.py` |
| QR timeout | Increase `QR_WAIT_TIMEOUT` in `config.py` |
| Message box not found | WhatsApp Web layout changed; update XPath in `whatsapp_bot.py` |
| App crashes on start | Ensure all requirements are installed: `pip install -r requirements.txt` |

---

## Dependencies

- `customtkinter` — Modern dark-mode UI
- `selenium` — Browser automation
- `webdriver-manager` — Auto ChromeDriver management
- `pandas` — Excel reading
- `openpyxl` — `.xlsx` engine
- `Pillow` — Image support
