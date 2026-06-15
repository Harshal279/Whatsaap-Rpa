"""
setup.py
--------
One-click setup script:
  1. Creates a virtual environment (venv)
  2. Upgrades pip
  3. Installs all requirements
  4. Generates the sample Excel file

Usage:
    python setup.py
"""

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
VENV = ROOT / "venv"
REQ = ROOT / "requirements.txt"


def run(cmd, **kwargs):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"[ERROR] Command failed with code {result.returncode}")
        sys.exit(result.returncode)


def main():
    print("=" * 60)
    print(" WhatsApp RPA Automator — Setup")
    print("=" * 60)

    # 1. Virtual environment
    if not VENV.exists():
        print("\n[1/4] Creating virtual environment…")
        run([sys.executable, "-m", "venv", str(VENV)])
    else:
        print("\n[1/4] Virtual environment already exists — skipping.")

    # Python executable inside venv
    python = str(VENV / ("Scripts" if os.name == "nt" else "bin") / "python")

    # 2. Upgrade pip
    print("\n[2/4] Upgrading pip…")
    run([python, "-m", "pip", "install", "--upgrade", "pip"])

    # 3. Install requirements
    print("\n[3/4] Installing requirements…")
    run([python, "-m", "pip", "install", "-r", str(REQ)])

    # 4. Generate sample Excel
    print("\n[4/4] Generating sample Excel file…")
    run([python, str(ROOT / "create_sample_excel.py")])

    print("\n" + "=" * 60)
    print(" Setup complete!")
    print(f" To run the app:  {python} main.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
