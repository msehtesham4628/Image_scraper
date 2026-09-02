import asyncio
import json
from urllib.parse import urljoin
from playwright.async_api import async_playwright


BASE_URL = "https://worldhookahmarket.com"
OUTPUT_FILE = "products.json"


async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Opening website...")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=120000)

        # Collect product links
        product_links = set()

        print("Finding product links...")

        # Scroll through pages to trigger lazy loading
        for _ in range(20):
            links = await page.locator("a[href]").evaluate_all(
                """els => els.map(e => e.href)"""
            )

            for link in links:
                if link.startswith(BASE_URL):
                    product_links.add(link)

            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(1000)

        # Keep likely product URLs
        product_links = {
            url for url in product_links
            if any(x in url.lower() for x in [
                "/product/",
                "/products/",
                "/p/"
            ])
        }

        print(f"Found {len(product_links)} possible product pages.")

        products = []

        for index, product_url in enumerate(product_links, 1):

            try:
                print(f"[{index}/{len(product_links)}] {product_url}")

                await page.goto(
                    product_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                await page.wait_for_timeout(1000)

                # Product name
                name = ""

                selectors = [
                    "h1",
                    "[itemprop='name']",
                    ".product-title",
                    ".product__title"
                ]

                for selector in selectors:
                    locator = page.locator(selector).first

                    if await locator.count():
                        text = await locator.inner_text()

                        if text.strip():
                            name = text.strip()
                            break

                # Description
                description = ""

                selectors = [
                    "[itemprop='description']",
                    ".product-description",
                    ".product__description",
                    ".description"
                ]

                for selector in selectors:
                    locator = page.locator(selector).first

                    if await locator.count():
                        text = await locator.inner_text()

                        if text.strip():
                            description = text.strip()
                            break

                # Price
                price = ""

                selectors = [
                    "[itemprop='price']",
                    ".price",
                    ".product-price",
                    ".product__price"
                ]

                for selector in selectors:
                    locator = page.locator(selector).first

                    if await locator.count():
                        text = await locator.inner_text()

                        if text.strip():
                            price = text.strip()
                            break

                # Image
                image_url = ""

                selectors = [
                    "[itemprop='image']",
                    ".product img",
                    ".product__media img",
                    "main img"
                ]

                for selector in selectors:
                    locator = page.locator(selector).first

                    if await locator.count():

                        image_url = await locator.get_attribute("src")

                        if not image_url:
                            image_url = await locator.get_attribute(
                                "data-src"
                            )

                        if image_url:
                            image_url = urljoin(
                                product_url,
                                image_url
                            )
                            break

                product = {
                    "product_name": name,
                    "description": description,
                    "price": price,
                    "image_url": image_url,
                    "product_url": product_url
                }

                # Don't save empty pages
                if name or price or image_url:
                    products.append(product)

                    # Save continuously so progress isn't lost
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

            except Exception as e:
                print("ERROR:", e)

        await browser.close()

        print()
        print("Finished!")
        print(f"Products saved: {len(products)}")
        print(f"File: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(scrape())