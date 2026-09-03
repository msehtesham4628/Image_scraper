import os
import re
import json
import time
import zipfile
import hashlib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque
from xml.etree import ElementTree as ET

# ============================================================
# WORLD HOOKAH MARKET SCRAPER
# - Skips ?add-to-cart= and other action/query URLs
# - Uses sitemap.xml when available
# - Crawls category/product links
# - Extracts products + images
# - Downloads unique images
# - Creates products.json + ZIP
# ============================================================

BASE_URL = "https://worldhookahmarket.com/"
DOMAIN = "worldhookahmarket.com"

OUTPUT_DIR = "worldhookahmarket_images"
ZIP_FILE = "worldhookahmarket_images.zip"
PRODUCTS_FILE = "products.json"

PAGE_TIMEOUT = 15
IMAGE_TIMEOUT = 20
MAX_RETRIES = 2

os.makedirs(OUTPUT_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})

visited = set()
queued = set()
image_urls = set()
products = []
product_urls = set()
queue = deque()


def clean_url(url):
    """Remove fragments and query strings so cart/action URLs are ignored."""
    if not url:
        return None

    url = url.strip()
    url = urljoin(BASE_URL, url)
    url, _ = urldefrag(url)

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return None

    host = parsed.netloc.lower()

    if host not in (DOMAIN, "www." + DOMAIN):
        return None

    # IMPORTANT:
    # WorldHookahMarket uses URLs such as:
    # /product/example/?add-to-cart=1234
    # These are cart actions, NOT pages to crawl.
    # Drop the entire query string.
    path = parsed.path or "/"

    # Normalize repeated slashes.
    path = re.sub(r"/+", "/", path)

    # Keep trailing slash for normal website URLs.
    return f"https://{DOMAIN}{path}"


def is_same_domain(url):
    try:
        host = urlparse(url).netloc.lower()
        return host in (DOMAIN, "www." + DOMAIN)
    except Exception:
        return False


def is_http_url(url):
    return url.startswith(("http://", "https://"))


def is_image_url(url):
    path = urlparse(url).path.lower()
    return path.endswith((
        ".jpg", ".jpeg", ".png", ".webp",
        ".gif", ".avif", ".svg", ".jfif"
    ))


def is_probably_product_url(url):
    path = urlparse(url).path.lower()
    return "/product/" in path


def add_page(url):
    url = clean_url(url)
    if not url:
        return

    if url not in visited and url not in queued:
        queued.add(url)
        queue.append(url)


def add_image(url, base_url):
    if not url:
        return

    url = url.strip()

    # Ignore srcset descriptors such as 300w.
    if url.endswith(("w", "x")) and not is_http_url(url):
        return

    image_url = urljoin(base_url, url)
    image_url, _ = urldefrag(image_url)

    if not is_http_url(image_url):
        return

    if is_same_domain(image_url) or urlparse(image_url).netloc:
        image_urls.add(image_url)


def get_page(url):
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=PAGE_TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text
            print(f"  HTTP {r.status_code}")
            return None
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                print(f"  Timeout/error; retry {attempt + 1}/{MAX_RETRIES}")
                time.sleep(1)
            else:
                print(f"  PAGE ERROR: {e}")
    return None


def extract_srcset(value, base_url):
    if not value:
        return

    for item in value.split(","):
        item = item.strip()
        if not item:
            continue

        # "image.jpg 768w" -> "image.jpg"
        parts = item.split()
        if parts:
            add_image(parts[0], base_url)


def extract_images(soup, page_url):
    # img tags
    for img in soup.find_all("img"):
        for attr in (
            "src", "data-src", "data-lazy-src",
            "data-original", "data-flickity-lazyload",
            "data-large_image", "data-image"
        ):
            add_image(img.get(attr), page_url)

        extract_srcset(img.get("srcset"), page_url)
        extract_srcset(img.get("data-srcset"), page_url)

    # <source srcset="">
    for source in soup.find_all("source"):
        extract_srcset(source.get("srcset"), page_url)
        add_image(source.get("src"), page_url)

    # OpenGraph / Twitter product images
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        content = meta.get("content")
        if prop and content:
            prop = prop.lower()
            if prop in (
                "og:image",
                "og:image:url",
                "twitter:image",
                "twitter:image:src",
            ):
                add_image(content, page_url)

    # Inline CSS background-image
    for tag in soup.find_all(style=True):
        styles = tag.get("style", "")
        for match in re.findall(r"url\(\s*[\"']?(.*?)[\"']?\s*\)", styles):
            add_image(match, page_url)


def text_of(element):
    if not element:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def extract_price(soup):
    # WooCommerce common price selectors
    selectors = [
        "p.price",
        "span.price",
        ".price",
        ".woocommerce-Price-amount",
        "meta[itemprop='price']",
    ]

    for selector in selectors:
        el = soup.select_one(selector)
        if not el:
            continue

        if el.name == "meta":
            value = el.get("content", "").strip()
        else:
            value = text_of(el)

        if value:
            return value

    # JSON-LD offers price fallback
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]

        for item in candidates:
            if not isinstance(item, dict):
                continue

            offers = item.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price")
                currency = offers.get("priceCurrency", "")
                if price:
                    return f"{currency} {price}".strip()

    return ""


def extract_product(soup, url):
    # Only treat real /product/ pages as products.
    if not is_probably_product_url(url):
        return None

    title = ""

    for selector in (
        "h1.product_title",
        "h1.entry-title",
        "h1",
        "meta[property='og:title']",
    ):
        el = soup.select_one(selector)
        if el:
            title = (
                el.get("content", "").strip()
                if el.name == "meta"
                else text_of(el)
            )
            if title:
                break

    if not title:
        return None

    description = ""

    for selector in (
        ".woocommerce-product-details__short-description",
        ".woocommerce-Tabs-panel--description",
        "#tab-description",
        ".product .description",
        "meta[property='og:description']",
    ):
        el = soup.select_one(selector)
        if el:
            description = (
                el.get("content", "").strip()
                if el.name == "meta"
                else text_of(el)
            )
            if description:
                break

    price = extract_price(soup)

    # Product main image + gallery
    product_images = []

    for selector in (
        ".woocommerce-product-gallery img",
        ".woocommerce-product-gallery__image img",
        ".product-images img",
        ".product img",
    ):
        for img in soup.select(selector):
            for attr in (
                "src", "data-src", "data-large_image",
                "data-lazy-src", "data-original"
            ):
                value = img.get(attr)
                if value:
                    img_url = urljoin(url, value)
                    if is_http_url(img_url):
                        product_images.append(img_url)

            srcset = img.get("srcset")
            if srcset:
                for item in srcset.split(","):
                    parts = item.strip().split()
                    if parts:
                        product_images.append(urljoin(url, parts[0]))

    # OpenGraph fallback
    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        product_images.append(urljoin(url, og["content"]))

    # Clean image list
    clean_images = []
    seen = set()

    for img_url in product_images:
        img_url = urldefrag(img_url)[0]
        if img_url not in seen:
            seen.add(img_url)
            clean_images.append(img_url)

    # Add all product images to global download list.
    for img_url in clean_images:
        image_urls.add(img_url)

    return {
        "name": title,
        "description": description,
        "price": price,
        "url": url,
        "images": clean_images,
    }


def load_sitemap():
    """Load sitemap URLs first. This is much better than blindly crawling links."""
    sitemap_candidates = [
        urljoin(BASE_URL, "sitemap_index.xml"),
        urljoin(BASE_URL, "wp-sitemap.xml"),
        urljoin(BASE_URL, "product-sitemap.xml"),
        urljoin(BASE_URL, "product-sitemap1.xml"),
        urljoin(BASE_URL, "robots.txt"),
    ]

    found = set()

    for sitemap_url in sitemap_candidates:
        try:
            r = session.get(sitemap_url, timeout=PAGE_TIMEOUT)
            if r.status_code != 200:
                continue

            text = r.text

            if sitemap_url.endswith("robots.txt"):
                for line in text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sm = line.split(":", 1)[1].strip()
                        if sm:
                            found.add(sm)
                continue

            # XML sitemap
            root = ET.fromstring(text)

            for loc in root.iter():
                if loc.tag.lower().endswith("loc") and loc.text:
                    found.add(loc.text.strip())

        except Exception as e:
            print("SITEMAP ERROR:", sitemap_url, e)

    # A sitemap index may point to other sitemaps.
    expanded = set(found)

    for sm_url in list(found):
        if not sm_url.startswith(("http://", "https://")):
            continue

        try:
            r = session.get(sm_url, timeout=PAGE_TIMEOUT)
            if r.status_code != 200:
                continue

            root = ET.fromstring(r.text)

            for loc in root.iter():
                if loc.tag.lower().endswith("loc") and loc.text:
                    expanded.add(loc.text.strip())

        except Exception:
            pass

    for item in expanded:
        clean = clean_url(item)
        if clean:
            add_page(clean)

    print(f"Sitemap/page URLs queued: {len(queue)}")


def crawl():
    print("=" * 65)
    print("STARTING WORLD HOOKAH MARKET SCRAPER")
    print("=" * 65)

    # Start with sitemap URLs.
    load_sitemap()

    # Always crawl homepage.
    add_page(BASE_URL)

    while queue:
        url = queue.popleft()
        queued.discard(url)

        if url in visited:
            continue

        visited.add(url)

        print(f"[PAGE {len(visited)}] {url}")

        html = get_page(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        extract_images(soup, url)

        product = extract_product(soup, url)
        if product:
            if url not in product_urls:
                product_urls.add(url)
                products.append(product)
                print(f"  PRODUCT: {product['name']}")

        # Discover normal internal pages.
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()

            if not href:
                continue

            # Explicitly ignore cart/action links.
            lower = href.lower()
            if (
                "add-to-cart" in lower
                or "remove_item" in lower
                or "wc-ajax" in lower
                or "checkout" in lower
                or "cart" in lower
                or "my-account" in lower
                or "logout" in lower
                or "wp-admin" in lower
            ):
                continue

            absolute = urljoin(url, href)
            clean = clean_url(absolute)

            if not clean:
                continue

            if is_image_url(clean):
                add_image(clean, url)
                continue

            if is_same_domain(clean):
                add_page(clean)

        # Also inspect canonical URL.
        canonical = soup.select_one("link[rel='canonical']")
        if canonical and canonical.get("href"):
            add_page(canonical["href"])

    print()
    print("=" * 65)
    print("CRAWL COMPLETE")
    print("Pages visited:", len(visited))
    print("Products found:", len(products))
    print("Images found:", len(image_urls))
    print("=" * 65)


def save_products():
    # Sort for stable output.
    products.sort(key=lambda x: x["name"].lower())

    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"Saved: {PRODUCTS_FILE}")


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "image"


def download_images():
    downloaded = 0
    failed = 0
    hashes = set()

    # Existing hashes so rerunning the scraper doesn't download duplicates.
    for root, _, files in os.walk(OUTPUT_DIR):
        for filename in files:
            path = os.path.join(root, filename)
            try:
                with open(path, "rb") as f:
                    hashes.add(hashlib.sha256(f.read()).hexdigest())
            except Exception:
                pass

    total = len(image_urls)

    print()
    print("=" * 65)
    print(f"DOWNLOADING {total} IMAGES")
    print("=" * 65)

    for index, image_url in enumerate(sorted(image_urls), 1):
        print(f"[IMAGE {index}/{total}] {image_url}")

        try:
            r = session.get(image_url, timeout=IMAGE_TIMEOUT)

            if r.status_code != 200:
                failed += 1
                print(f"  HTTP {r.status_code}")
                continue

            content = r.content

            if len(content) < 300:
                failed += 1
                print("  Too small - skipped")
                continue

            file_hash = hashlib.sha256(content).hexdigest()

            if file_hash in hashes:
                print("  Duplicate - skipped")
                continue

            hashes.add(file_hash)

            parsed = urlparse(image_url)
            original = os.path.basename(parsed.path)

            if not original:
                original = f"image_{downloaded + 1}.jpg"

            filename = safe_filename(original)
            base, ext = os.path.splitext(filename)

            if not ext:
                ext = ".jpg"

            filepath = os.path.join(OUTPUT_DIR, filename)
            counter = 1

            while os.path.exists(filepath):
                filepath = os.path.join(
                    OUTPUT_DIR,
                    f"{base}_{counter}{ext}"
                )
                counter += 1

            with open(filepath, "wb") as f:
                f.write(content)

            downloaded += 1

        except requests.RequestException as e:
            failed += 1
            print("  IMAGE ERROR:", e)

    print()
    print("=" * 65)
    print("IMAGE DOWNLOAD COMPLETE")
    print("Downloaded:", downloaded)
    print("Failed:", failed)
    print("=" * 65)


def create_zip():
    print("Creating ZIP...")

    with zipfile.ZipFile(
        ZIP_FILE,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as zipf:

        for root, _, files in os.walk(OUTPUT_DIR):
            for filename in files:
                filepath = os.path.join(root, filename)
                arcname = os.path.relpath(filepath, OUTPUT_DIR)
                zipf.write(filepath, arcname)

    print(f"ZIP created: {ZIP_FILE}")


if __name__ == "__main__":
    try:
        crawl()
        save_products()
        download_images()
        create_zip()

        print()
        print("=" * 65)
        print("DONE!")
        print(f"Products JSON : {PRODUCTS_FILE}")
        print(f"Images folder : {OUTPUT_DIR}")
        print(f"Images ZIP    : {ZIP_FILE}")
        print("=" * 65)

    except KeyboardInterrupt:
        print("\nSTOPPED BY USER")
        save_products()
        print("Progress saved to products.json")
