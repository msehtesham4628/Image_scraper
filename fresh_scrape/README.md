# Fresh WHM Scrape

This folder is an isolated workspace for the new catalog scrape.

- Existing `products.json` and `products_progress.json` in the repository root are not used by the fresh run.
- Fresh output is written here in chunks of 1,000 products.
- Files are created as `products-1.json`, `products-2.json`, etc.
- Progress is saved as `progress.json`.

Run from the repository root:

```bash
FRESH_SCRAPE=1 python scraper.py
```
