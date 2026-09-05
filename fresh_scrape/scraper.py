# Dedicated fresh scrape entrypoint.
# It imports the main scraper, which writes all fresh output under fresh_scrape/.
# Run from this folder with: FRESH_SCRAPE=1 python scraper.py
import os
import sys

os.environ["FRESH_SCRAPE"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scraper import main

if __name__ == "__main__":
    main()
