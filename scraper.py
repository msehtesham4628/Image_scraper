import json
import os
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://worldhookahmarket.com"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRESH_DIR = os.path.join(ROOT_DIR, "fresh_scrape")
PROGRESS_FILE = os.path.join(FRESH_DIR, "progress.json")
PART_SIZE = 1000
FRESH_SCRAPE = os.getenv("FRESH_SCRAPE", "0") == "1"

BLOCKED_PATH_PATTERNS = [
    r"^/(cart|checkout|my-account|wishlist|clients|wholesale)",
    r"^/(terms|privacy-policy|refund-policy|shipping-policy|contact-us|about-us)",
    r"^/(blog|news|article|category/blog)",
    r"^/wp-(login|admin|content/uploads/woocommerce-placeholder)",
    r"/(feed|trackback|xmlrpc\.php)",
]

ALLOWED_CRAWL_PATTERNS = [
    r"^/$",
    r"^/shop/?",
    r"^/product-category/[^/]+/?",
    r"^/category/[^/]+/?",
    r"^/brand/[^/]+/?",
    r"^/page/\d+/?",
]

IMAGE_BLACKLIST = {
    "logo", "icon", "cart", "svgrepo", "subscribe", "wait-time", "spinner",
    "loading", "placeholder", "avatar", "gravatar", "favicon", "payment",
    "visa", "mastercard", "amex", "discover", "paypal", "applepay",
    "facebook", "instagram", "youtube", "twitter", "whatsapp", "tiktok",
    "badge", "shield", "verified", "star", "rating", "truck", "shipping"
}

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
})

def clean_url(url: str) -> str:
    if not url:
        return ""
    p = urlparse(url)
    clean_path = re.sub(r"/+", "/", p.path).rstrip("/")
    return urlunparse((p.scheme.lower(), p.netloc.lower(), clean_path, "", "", ""))

def is_same_domain(url: str) -> bool:
    return urlparse(url).netloc.lower() in {"worldhookahmarket.com", "www.worldhookahmarket.com"}

def is_product_url(url: str) -> bool:
    return bool(re.search(r"^/product/[^/]+/?$", urlparse(url).path.lower()))

def should_crawl(url: str) -> bool:
    if not is_same_domain(url):
        return False
    path = urlparse(url).path.lower()
    for pattern in BLOCKED_PATH_PATTERNS:
        if re.search(pattern, path):
            return False
    for pattern in ALLOWED_CRAWL_PATTERNS:
        if re.search(pattern, path):
            return True
    return False

def get_page(url: str) -> str | None:
    try:
        res = session.get(url, timeout=25)
        if res.status_code == 200:
            return res.text
    except requests.RequestException as e:
        print(f"Fetch failed for {url}: {e}")
    return None

def text_one(soup: BeautifulSoup, selectors: list[str]) -> str:
    for s in selectors:
        elem = soup.select_one(s)
        if elem:
            txt = elem.get_text(" ", strip=True)
            if txt:
                return txt
    return ""

def parse_price(val) -> str:
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(val or "").replace(",", ""))
    return f"{float(m.group(1)):.2f}" if m else "0.00"

def is_valid_image(url: str) -> bool:
    u = url.lower()
    if not u.startswith("http") or u.startswith("data:"):
        return False
    if any(term in u for term in IMAGE_BLACKLIST):
        return False
    base_path = urlparse(u).path
    return any(base_path.endswith(ext) for ext in IMAGE_EXTENSIONS)

def parse_product_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text())
            nodes = payload if isinstance(payload, list) else payload.get("@graph", [payload]) if isinstance(payload, dict) else []
            for item in nodes:
                if isinstance(item, dict) and str(item.get("@type", "")).lower() == "product":
                    return item
        except (json.JSONDecodeError, TypeError):
            continue
    return {}

def extract_images(soup: BeautifulSoup, base_url: str, jsonld: dict) -> list[str]:
    seen = set()
    results = []

    def register(raw_url: str):
        if not raw_url:
            return
        full = clean_url(urljoin(base_url, raw_url.strip()))
        if full and full not in seen and is_valid_image(full):
            seen.add(full)
            results.append(full)

    selectors = [
        ".woocommerce-product-gallery__image a",
        ".woocommerce-product-gallery__wrapper img",
        ".woocommerce-product-gallery img",
        ".product-images img",
    ]
    for s in selectors:
        for node in soup.select(s):
            register(node.get("href"))
            for attr in ("data-large_image", "data-src", "data-original", "src"):
                register(node.get(attr))
            srcset = node.get("srcset") or node.get("data-srcset")
            if srcset:
                for part in srcset.split(","):
                    chunk = part.strip().split()
                    if chunk:
                        register(chunk[0])

    if not results and jsonld:
        imgs = jsonld.get("image", [])
        imgs = [imgs] if isinstance(imgs, str) else imgs
        for item in imgs:
            if isinstance(item, str):
                register(item)

    return results[:20]

def extract(url: str) -> dict | None:
    html = get_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    ld = parse_product_jsonld(soup)

    # 1. Product Name
    name = (ld.get("name") if ld else "") or text_one(soup, ["h1.product_title", "h1.entry-title", "h1"])
    name = str(name).strip()

    # 2. Description
    desc = (ld.get("description") if ld else "") or text_one(soup, [
        ".woocommerce-product-details__short-description",
        "#tab-description",
        ".product-description"
    ])
    desc = str(desc).strip()

    # 3. Price
    price = "0.00"
    if ld and isinstance(ld.get("offers"), (dict, list)):
        offers = ld["offers"][0] if isinstance(ld["offers"], list) and ld["offers"] else ld["offers"]
        if isinstance(offers, dict):
            price = parse_price(offers.get("price"))
    if price == "0.00":
        price = parse_price(text_one(soup, [".price ins .amount", ".price .amount", ".price"]))

    # 4. SKU
    sku = (ld.get("sku") if ld else "") or text_one(soup, [".sku_wrapper .sku", ".sku"])
    sku = str(sku).strip()

    # 5. Image URLs
    imgs = extract_images(soup, url, ld)

    # 6. Product URL
    prod_url = clean_url(url)

    if not name and price == "0.00" and not imgs:
        return None

    return {
        "product_name": name,
        "description": desc,
        "price": price,
        "sku": sku,
        "image_urls": imgs,
        "product_url": prod_url
    }

def collect_product_urls() -> list[str]:
    queue = deque([BASE_URL, f"{BASE_URL}/shop/"])
    crawled = set()
    found_products = set()

    while queue:
        current = clean_url(queue.popleft())
        if current in crawled or not is_same_domain(current):
            continue
        crawled.add(current)
        print(f"[CRAWL {len(crawled):03d}] {current}")

        html = get_page(current)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("a", href=True):
            clean_target = clean_url(urljoin(current, tag["href"]))
            if is_product_url(clean_target):
                found_products.add(clean_target)
            elif clean_target not in crawled and should_crawl(clean_target):
                queue.append(clean_target)

        time.sleep(0.05)

    print(f"Crawl finished. Found {len(found_products)} product URLs.")
    return sorted(found_products)

def save_parts(products: list[dict]):
    os.makedirs(FRESH_DIR, exist_ok=True)
    for fn in os.listdir(FRESH_DIR):
        if re.fullmatch(r"products-\d+\.json", fn):
            try:
                os.remove(os.path.join(FRESH_DIR, fn))
            except OSError:
                pass

    for i in range(0, len(products), PART_SIZE):
        idx = (i // PART_SIZE) + 1
        path = os.path.join(FRESH_DIR, f"products-{idx}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(products[i:i + PART_SIZE], f, ensure_ascii=False, indent=2)

def main():
    os.makedirs(FRESH_DIR, exist_ok=True)
    products = []
    scraped_urls = set()

    if not FRESH_SCRAPE and os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                products = json.load(f)
                scraped_urls = {p["product_url"] for p in products if "product_url" in p}
            print(f"Loaded {len(products)} existing records.")
        except Exception as e:
            print(f"Could not load {PROGRESS_FILE}: {e}")

    urls = collect_product_urls()
    remaining = [u for u in urls if u not in scraped_urls]
    print(f"Targeting {len(remaining)} unscraped product pages.")

    for idx, target_url in enumerate(remaining, start=1):
        print(f"[{idx}/{len(remaining)}] {target_url}")
        try:
            data = extract(target_url)
            if data:
                products.append(data)
                print(f"  ✓ {data['product_name'][:35]} | ${data['price']} | SKU: {data['sku']} | Imgs: {len(data['image_urls'])}")
        except Exception as e:
            print(f"  ✗ Error on {target_url}: {e}")

        if idx % 50 == 0:
            save_parts(products)
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(products, f, ensure_ascii=False, indent=2)

        time.sleep(0.15)

    save_parts(products)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"Extraction completed: {len(products)} records saved.")

if __name__ == "__main__":
    main()
