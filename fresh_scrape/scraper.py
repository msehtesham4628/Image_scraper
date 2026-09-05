import os
import sys

# 1. Force fresh scrape mode before any imports
os.environ["FRESH_SCRAPE"] = "1"

# 2. Resolve paths cleanly
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# If this file is in a subfolder (e.g., scripts/run_fresh.py), resolve project root:
ROOT_DIR = os.path.dirname(CURRENT_DIR) if os.path.basename(CURRENT_DIR) != "scraper" else CURRENT_DIR

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 3. Import and execute main
try:
    from scraper import main, FRESH_DIR
    print(f"[*] Starting Fresh Scrape...")
    print(f"[*] Target Directory: {FRESH_DIR}")
    
    if __name__ == "__main__":
        main()
except ImportError as e:
    print(f"[!] Import Error: Could not find 'scraper.py' in {ROOT_DIR}")
    print(f"    Details: {e}")
