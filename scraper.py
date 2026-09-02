import json
import os
import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://worldhookahmarket.com"
OUTPUT_FILE = "products.json"
PROGRESS_FILE = "products_progress.json"

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    )
})


def clean_url(url):
    """Remove tracking/query parameters."""
    parsed = urlparse(url)

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        "",
        "",
        ""
    ))


def is_product_url(url):
    url = clean_url(url).lower()

    return (
        "/product/" in url
        or "/products/" in url
        or "/p/" in url
    )


def same_domain(url):
    host = urlparse(url).netloc.lower()

    return host in {
        "worldhookahmarket.com",
        "www.worldhookahmarket.com"
    }


def get_page(url):
    try:
        response = session.get(
            url,
            timeout=60
        )

        if response.status_code == 200:
            return response.text

        print(
            f"HTTP {response.status_code}: {url}"
        )

    except Exception as e:
        print(f"REQUEST ERROR: {e}")

    return None


def get_text(soup, selectors):
    for selector in selectors:

        element = soup.select_one(selector)

        if element:

            text = element.get_text(
                " ",
                strip=True
            )

            if text:
                return text

    return ""


def get_images(soup, page_url):
    images = set()

    for img in soup.find_all("img"):

        attributes = [
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "data-image",
            "data-large-image"
        ]

        for attribute in attributes:

            value = img.get(attribute)

            if value:
                images.add(
                    urljoin(page_url, value)
                )

        # srcset
        for attribute in [
            "srcset",
            "data-srcset"
        ]:

            value = img.get(attribute)

            if not value:
                continue

            for item in value.split(","):

                item = item.strip()

                if not item:
                    continue

                image = item.split()[0]

                images.add(
                    urljoin(page_url, image)
                )

    return list(images)


def extract_product(url):
    html = get_page(url)

    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Product name
    name = get_text(
        soup,
        [
            "h1.product_title",
            "h1.product-title",
            "h1",
            "[itemprop='name']"
        ]
    )

    # Description
    description = get_text(
        soup,
        [
            ".woocommerce-product-details__short-description",
            ".product-description",
            ".product__description",
            "[itemprop='description']",
            ".description"
        ]
    )

    # Price
    price = ""

    price_element = soup.select_one(
        "[itemprop='price']"
    )

    if price_element:
        price = (
            price_element.get("content")
            or price_element.get_text(
                " ",
                strip=True
            )
        )

    if not price:

        price = get_text(
            soup,
            [
                ".price",
                ".product-price",
                ".product__price"
            ]
        )

    # SKU
    sku = get_text(
        soup,
        [
            ".sku",
            "[itemprop='sku']"
        ]
    )

    # Images
    images = get_images(
        soup,
        url
    )

    # Remove obvious tiny/icon images
    images = [
        image for image in images
        if image.startswith("http")
    ]

    if not name and not price and not images:
        return None

    return {
        "product_name": name,
        "description": description,
        "price": price,
        "sku": sku,
        "image_urls": images,
        "product_url": url
    }


def save_products(products):

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            products,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_existing():

    if not os.path.exists(
        PROGRESS_FILE
    ):
        return []

    try:

        with open(
            PROGRESS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except:
        return []


def collect_links():

    print("Starting website crawl...")
    print()

    pages_to_visit = [
        BASE_URL
    ]

    visited = set()
    product_links = set()

    while pages_to_visit:

        url = pages_to_visit.pop(0)

        url = clean_url(url)

        if url in visited:
            continue

        if not same_domain(url):
            continue

        visited.add(url)

        print(
            f"[PAGE {len(visited)}] {url}"
        )

        html = get_page(url)

        if not html:
            continue

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = urljoin(
                url,
                a["href"]
            )

            if not same_domain(href):
                continue

            href = clean_url(href)

            # Product
            if is_product_url(href):

                product_links.add(href)

            # Continue crawling internal pages
            else:

                if href not in visited:
                    pages_to_visit.append(href)

        # Also follow pagination
        for a in soup.select(
            "a.page-numbers, "
            "a.next, "
            "a.next.page-numbers"
        ):

            href = a.get("href")

            if href:

                href = clean_url(
                    urljoin(
                        url,
                        href
                    )
                )

                if (
                    same_domain(href)
                    and href not in visited
                ):
                    pages_to_visit.append(
                        href
                    )

        # Prevent an accidental enormous crawl
        if len(visited) % 50 == 0:

            print(
                f"  Products discovered: "
                f"{len(product_links)}"
            )

        time.sleep(0.1)

    print()
    print("=" * 60)
    print("CRAWL COMPLETE")
    print(
        f"Pages visited: {len(visited)}"
    )
    print(
        f"Products found: {len(product_links)}"
    )
    print("=" * 60)
    print()

    return sorted(product_links)


def scrape_products(product_links):

    products = load_existing()

    completed_urls = {
        p.get("product_url")
        for p in products
    }

    print(
        f"Already saved: {len(products)}"
    )

    print()

    for index, url in enumerate(
        product_links,
        1
    ):

        if url in completed_urls:

            print(
                f"[{index}/{len(product_links)}] "
                f"SKIP {url}"
            )

            continue

        print(
            f"[{index}/{len(product_links)}] "
            f"{url}"
        )

        try:

            product = extract_product(
                url
            )

            if product:

                products.append(
                    product
                )

                save_products(
                    products
                )

                with open(
                    PROGRESS_FILE,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        products,
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

                print(
                    f"  ✓ {product['product_name']}"
                )

                print(
                    f"  Images: "
                    f"{len(product['image_urls'])}"
                )

            else:

                print(
                    "  No product data"
                )

        except Exception as e:

            print(
                f"  ERROR: {e}"
            )

        time.sleep(0.3)

    return products


def main():

    product_links = collect_links()

    if not product_links:

        print(
            "No products found."
        )

        return

    products = scrape_products(
        product_links
    )

    save_products(
        products
    )

    print()
    print("=" * 60)
    print("FINISHED")
    print(
        f"Products saved: {len(products)}"
    )

    total_images = sum(
        len(p.get("image_urls", []))
        for p in products
    )

    print(
        f"Image URLs saved: {total_images}"
    )

    print(
        f"JSON file: {OUTPUT_FILE}"
    )

    print("=" * 60)


if __name__ == "__main__":
    main()