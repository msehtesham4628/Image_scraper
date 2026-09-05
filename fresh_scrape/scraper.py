import json
import os
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://worldhookahmarket.com"
# Save directly in the current folder where scraper.py lives
SAVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(SAVE_DIR, "progress.json")
PART_SIZE = 1000

BLOCKED_PATTERNS = [
    r"^/(cart|checkout|my-account|wishlist|clients|wholesale)",
    r"^/(terms|privacy-policy|refund-policy|shipping-policy|contact-us|about-us)",
    r"^/(blog|news|article)",
    r"^/wp-(login|admin)",
]

ALLOWED_PATTERNS = [
    r"^/$",
    r"^/shop/?",
    r"^/product-category/",
    r"^/category/",
    r"^/brand/",
    r"^/page/\d+/?",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
})

def clean_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme.lower(), p.netloc.lower(), re.sub(r"/+", "/", p.path).rstrip("/"), "", "", ""))

def is_same_domain(url):
    return urlparse(url).netloc.lower() in {"worldhookahmarket.com", "www.worldhookahmarket.com"}

def is_product(url):
    return bool(re.search(r"^/product/[^/]+/?$", urlparse(url).path.lower()))

def should_crawl(url):
    if not is_same_domain(url):
        return False
    path = urlparse(url).path.lower()
    if any(re.search(p, path) for p in BLOCKED_PATTERNS):
        return False
    return any(re.search(p, path) for p in ALLOWED_PATTERNS)

def get_page(url):
    try:
        r = session.get(url, timeout=20)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None

def parse_price(val):
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(val or "").replace(",", ""))
    return f"{float(m.group(1)):.2f}" if m else "0.00"

def get_images(soup, base_url):
    imgs = []
    seen = set()
    for img in soup.select(".woocommerce-product-gallery img, .product-images img"):
        src = img.get("data-large_image") or img.get("data-src") or img.get("src")
        if src:
            full = clean_url(urljoin(base_url, src))
            if full.startswith("http") and full not in seen and not any(x in full for x in ("logo", "icon", "cart")):
                seen.add(full)
                imgs.append(full)
    return imgs[:20]

def extract_product(html, url):
    soup = BeautifulSoup(html, "html.parser")
    name = soup.select_one("h1.product_title, h1")
    name = name.get_text(strip=True) if name else ""

    desc = soup.select_one(".woocommerce-product-details__short-description, #tab-description")
    desc = desc.get_text(" ", strip=True) if desc else ""

    price_elem = soup.select_one(".price ins .amount, .price .amount, .price")
    price = parse_price(price_elem.get_text(strip=True) if price_elem else "")

    sku_elem = soup.select_one(".sku")
    sku = sku_elem.get_text(strip=True) if sku_elem else ""

    return {
        "product_name": name,
        "description": desc,
        "price": price,
        "sku": sku,
        "image_urls": get_images(soup, url),
        "product_url": clean_url(url)
    }

def save_files(products):
    for i in range(0, len(products), PART_SIZE):
        idx = (i // PART_SIZE) + 1
        path = os.path.join(SAVE_DIR, f"products-{idx}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(products[i:i + PART_SIZE], f, indent=2, ensure_ascii=False)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

def main():
    queue = deque([BASE_URL, f"{BASE_URL}/shop/"])
    crawled = set()
    scraped_products = []
    seen_products = set()

    print(f"Saving JSON files directly to: {SAVE_DIR}")

    # Immediately write empty progress file so it shows in VS Code
    save_files([])

    while queue:
        url = clean_url(queue.popleft())
        if url in crawled or not is_same_domain(url):
            continue
        crawled.add(url)

        html = get_page(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        # If the page itself is a product, extract immediately
        if is_product(url) and url not in seen_products:
            seen_products.add(url)
            data = extract_product(html, url)
            if data["product_name"]:
                scraped_products.append(data)
                print(f"[{len(scraped_products)}] Scraped: {data['product_name'][:35]} | ${data['price']}")
                
                # Save immediately every 5 items so JSON updates in real-time
                if len(scraped_products) % 5 == 0:
                    save_files(scraped_products)
                    print(f" >> Updated {PROGRESS_FILE}")

        # Collect next links
        for a in soup.find_all("a", href=True):
            target = clean_url(urljoin(url, a["href"]))
            if is_product(target) and target not in seen_products:
                queue.append(target)
            elif should_crawl(target) and target not in crawled:
                queue.append(target)

        time.sleep(0.05)

    save_files(scraped_products)
    print("Complete.")

if __name__ == "__main__":
    main()
