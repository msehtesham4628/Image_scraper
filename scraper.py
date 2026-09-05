import json
import os
import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

BASE_URL = "https://worldhookahmarket.com"
OUTPUT_FILE = "products.json"
PROGRESS_FILE = "products_progress.json"
FRESH_SCRAPE = os.getenv("FRESH_SCRAPE", "0") == "1"

import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36"})


def clean_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))


def is_product_url(url):
    u = clean_url(url).lower()
    return "/product/" in u or "/products/" in u or "/p/" in u


def same_domain(url):
    return urlparse(url).netloc.lower() in {"worldhookahmarket.com", "www.worldhookahmarket.com"}


def get_page(url):
    try:
        r = session.get(url, timeout=60)
        if r.status_code == 200:
            return r.text
        print(f"HTTP {r.status_code}: {url}")
    except Exception as e:
        print(f"REQUEST ERROR: {e}")
    return None


def text_one(soup, selectors):
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


def jsonld_objects(soup):
    out = []
    for node in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(node.string or node.get_text())
            if isinstance(data, list): out.extend(data)
            elif isinstance(data, dict) and isinstance(data.get("@graph"), list): out.extend(data["@graph"])
            elif isinstance(data, dict): out.append(data)
        except Exception:
            pass
    return out


def find_product_jsonld(soup):
    for obj in jsonld_objects(soup):
        if isinstance(obj, dict) and str(obj.get("@type", "")).lower() == "product":
            return obj
    return {}


def is_bad_image(url):
    u = url.lower()
    return any(x in u for x in ("logo", "cart-svgrepo", "subscribe", "wait-time", "spinner", "loading", "placeholder", "avatar", "gravatar", "favicon", "payment", "facebook", "instagram", "youtube", "twitter", "whatsapp"))


def get_product_images(soup, page_url):
    selectors = [".woocommerce-product-gallery__wrapper img", ".woocommerce-product-gallery img", ".product-gallery img", ".product-images img", ".product__images img", ".single-product img.wp-post-image"]
    urls, seen = [], set()
    for selector in selectors:
        for img in soup.select(selector):
            values = [img.get(a) for a in ("data-large_image", "data-src", "data-lazy-src", "data-original", "src")]
            srcset = img.get("data-srcset") or img.get("srcset")
            if srcset: values.extend(x.strip().split()[0] for x in srcset.split(",") if x.strip())
            for value in values:
                if not value: continue
                u = urljoin(page_url, str(value).strip())
                if u.startswith("http") and u not in seen and not is_bad_image(u):
                    seen.add(u); urls.append(u)
        if urls: break
    if not urls:
        obj = find_product_jsonld(soup)
        images = obj.get("image", []) if isinstance(obj, dict) else []
        if isinstance(images, str): images = [images]
        for value in images if isinstance(images, list) else []:
            u = urljoin(page_url, str(value).strip())
            if u.startswith("http") and u not in seen and not is_bad_image(u):
                seen.add(u); urls.append(u)
    return urls[:20]


def parse_price(value):
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(value or "").replace(",", ""))
    return f"{float(m.group(1)):.2f}" if m else "0.00"


def extract_brand_category(soup, obj):
    brand = category = ""
    if isinstance(obj, dict):
        b = obj.get("brand")
        brand = str(b.get("name") or "").strip() if isinstance(b, dict) else str(b or "").strip()
        c = obj.get("category")
        category = str(c[0]).strip() if isinstance(c, list) and c else str(c or "").strip()
    brand = brand or text_one(soup, [".product_meta .brand", ".product-brand", ".brand-name", "[itemprop='brand']"])
    category = category or text_one(soup, [".product_meta .posted_in", ".product-category", ".product-categories", "[itemprop='category']"])
    if not category:
        crumbs = [x.get_text(" ", strip=True) for x in soup.select(".breadcrumb a, .breadcrumbs a, nav.woocommerce-breadcrumb a")]
        crumbs = [x for x in crumbs if x and x.lower() not in {"home", "shop"}]
        if crumbs: category = crumbs[-1]
    return brand, category


def extract_product(url):
    html = get_page(url)
    if not html: return None
    soup = BeautifulSoup(html, "html.parser")
    obj = find_product_jsonld(soup)
    name = str(obj.get("name") or "").strip() if obj else ""
    name = name or text_one(soup, ["h1.product_title", "h1.product-title", "h1", "[itemprop='name']"])
    description = str(obj.get("description") or "").strip() if obj else ""
    description = description or text_one(soup, [".woocommerce-product-details__short-description", ".product-description", ".product__description", "[itemprop='description']", ".description"])
    price = "0.00"
    if obj:
        offers = obj.get("offers")
        if isinstance(offers, list): offers = offers[0] if offers else {}
        if isinstance(offers, dict): price = parse_price(offers.get("price"))
    if price == "0.00":
        pe = soup.select_one("[itemprop='price']")
        price = parse_price(pe.get("content") if pe else "")
    if price == "0.00": price = parse_price(text_one(soup, [".price", ".product-price", ".product__price"]))
    sku = str(obj.get("sku") or "").strip() if obj else ""
    sku = sku or text_one(soup, [".sku", "[itemprop='sku']"])
    brand, category = extract_brand_category(soup, obj)
    images = get_product_images(soup, url)
    if not name and price == "0.00" and not images: return None
    return {"product_name": name, "description": description, "price": price, "sku": sku, "brand": brand, "category": category, "image_urls": images, "product_url": clean_url(url)}


def save_products(products):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f: json.dump(products, f, ensure_ascii=False, indent=2)


def load_existing():
    if FRESH_SCRAPE or not os.path.exists(PROGRESS_FILE): return []
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f: data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception: return []


def collect_links():
    print(f"Starting website crawl... Fresh scrape: {'YES' if FRESH_SCRAPE else 'NO'}")
    pages, visited, product_links = [BASE_URL], set(), set()
    while pages:
        url = clean_url(pages.pop(0))
        if url in visited or not same_domain(url): continue
        visited.add(url); print(f"[PAGE {len(visited)}] {url}")
        html = get_page(url)
        if not html: continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = clean_url(urljoin(url, a["href"]))
            if not same_domain(href): continue
            if is_product_url(href): product_links.add(href)
            elif href not in visited: pages.append(href)
        for a in soup.select("a.page-numbers, a.next, a.next.page-numbers"):
            href = a.get("href")
            if href:
                href = clean_url(urljoin(url, href))
                if same_domain(href) and href not in visited: pages.append(href)
        if len(visited) % 50 == 0: print(f"  Products discovered: {len(product_links)}")
        time.sleep(0.1)
    print(f"CRAWL COMPLETE — Pages: {len(visited)} — Products: {len(product_links)}")
    return sorted(product_links)


def scrape_products(product_links):
    products = load_existing()
    completed = {clean_url(p.get("product_url", "")) for p in products}
    print(f"Already saved: {len(products)}")
    for index, url in enumerate(product_links, 1):
        if not FRESH_SCRAPE and clean_url(url) in completed:
            print(f"[{index}/{len(product_links)}] SKIP {url}"); continue
        print(f"[{index}/{len(product_links)}] {url}")
        try:
            product = extract_product(url)
            if product:
                products.append(product); save_products(products)
                with open(PROGRESS_FILE, "w", encoding="utf-8") as f: json.dump(products, f, ensure_ascii=False, indent=2)
                print(f"  ✓ {product['product_name']} | {product['brand']} | {product['category']} | Images: {len(product['image_urls'])}")
        except Exception as e: print(f"  ERROR: {e}")
        time.sleep(0.3)
    return products


def main():
    links = collect_links()
    if not links: print("No products found."); return
    products = scrape_products(links); save_products(products)
    print(f"FINISHED — Products: {len(products)} — Image URLs: {sum(len(p.get('image_urls', [])) for p in products)}")


if __name__ == "__main__": main()
