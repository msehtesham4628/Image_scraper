import os
import re
import zipfile
import hashlib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque

BASE_URL = "https://worldhookahmarket.com/"
DOMAIN = "worldhookahmarket.com"

OUTPUT_DIR = "worldhookahmarket_images"
ZIP_FILE = "worldhookahmarket_images.zip"

os.makedirs(OUTPUT_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
})

visited_pages = set()
image_urls = set()
queue = deque([BASE_URL])


def normalize_url(url):
    url = url.split("#")[0]
    return url.rstrip("/")


def is_same_domain(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == DOMAIN or host == "www." + DOMAIN
    except:
        return False


def is_image_url(url):
    path = urlparse(url).path.lower()

    extensions = (
        ".jpg", ".jpeg", ".png", ".webp",
        ".gif", ".avif", ".svg"
    )

    return path.endswith(extensions)


def get_page(url):
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print("PAGE ERROR:", url, e)

    return None


print("Starting website crawl...")

while queue:
    url = normalize_url(queue.popleft())

    if url in visited_pages:
        continue

    if not is_same_domain(url):
        continue

    visited_pages.add(url)

    print(f"[PAGE {len(visited_pages)}] {url}")

    html = get_page(url)

    if not html:
        continue

    soup = BeautifulSoup(html, "html.parser")

    # Find normal image URLs
    for img in soup.find_all("img"):

        attributes = [
            img.get("src"),
            img.get("data-src"),
            img.get("data-lazy-src"),
            img.get("data-original"),
            img.get("srcset"),
            img.get("data-srcset")
        ]

        for value in attributes:

            if not value:
                continue

            # Handle srcset
            values = value.split(",")

            for item in values:
                item = item.strip()

                if " " in item:
                    item = item.split(" ")[0]

                image_url = urljoin(url, item)

                if image_url.startswith("http"):
                    image_urls.add(image_url)

    # Find CSS/background images
    for tag in soup.find_all(style=True):

        styles = tag.get("style", "")

        matches = re.findall(
            r'url\(["\']?(.*?)["\']?\)',
            styles
        )

        for match in matches:
            image_url = urljoin(url, match)

            if image_url.startswith("http"):
                image_urls.add(image_url)

    # Find links to images
    for link in soup.find_all("a", href=True):

        href = urljoin(url, link["href"])

        if is_image_url(href):
            image_urls.add(href)

        elif is_same_domain(href):
            if href not in visited_pages:
                queue.append(href)

print()
print("=" * 60)
print("CRAWL COMPLETE")
print("Pages found:", len(visited_pages))
print("Images found:", len(image_urls))
print("=" * 60)


# Download images
downloaded = 0
failed = 0
hashes = set()

for index, image_url in enumerate(sorted(image_urls), 1):

    try:

        print(f"[IMAGE {index}/{len(image_urls)}] {image_url}")

        r = session.get(image_url, timeout=30)

        if r.status_code != 200:
            failed += 1
            continue

        content = r.content

        if len(content) < 500:
            failed += 1
            continue

        # Remove duplicate images using SHA256
        file_hash = hashlib.sha256(content).hexdigest()

        if file_hash in hashes:
            print("  Duplicate - skipped")
            continue

        hashes.add(file_hash)

        parsed = urlparse(image_url)

        filename = os.path.basename(parsed.path)

        if not filename:
            filename = f"image_{downloaded + 1}.jpg"

        filename = re.sub(
            r'[<>:"/\\|?*]',
            "_",
            filename
        )

        # Prevent duplicate filenames
        base, ext = os.path.splitext(filename)

        filepath = os.path.join(
            OUTPUT_DIR,
            filename
        )

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

    except Exception as e:

        failed += 1
        print("  ERROR:", e)


print()
print("=" * 60)
print("DOWNLOAD COMPLETE")
print("Downloaded:", downloaded)
print("Failed:", failed)
print("=" * 60)


# Create ZIP
print("Creating ZIP...")

with zipfile.ZipFile(
    ZIP_FILE,
    "w",
    compression=zipfile.ZIP_DEFLATED
) as zipf:

    for root, dirs, files in os.walk(OUTPUT_DIR):

        for file in files:

            filepath = os.path.join(root, file)

            arcname = os.path.relpath(
                filepath,
                OUTPUT_DIR
            )

            zipf.write(
                filepath,
                arcname
            )

print()
print("=" * 60)
print("DONE!")
print("ZIP:", ZIP_FILE)
print("=" * 60)