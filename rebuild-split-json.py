import json
from pathlib import Path

INPUT = Path("products.json")
OUTPUT_DIR = Path("split_products")
PARTS = 4


def main():
    with INPUT.open("r", encoding="utf-8") as f:
        products = json.load(f)

    if not isinstance(products, list):
        raise ValueError("products.json must contain a JSON array")

    # Keep only complete object records and remove exact duplicate product URLs/SKUs.
    deduped = []
    seen = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        key = str(product.get("product_url") or product.get("sku") or product.get("product_name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(product)

    OUTPUT_DIR.mkdir(exist_ok=True)
    for old in OUTPUT_DIR.glob("products-*.json"):
        old.unlink()

    total = len(deduped)
    chunk_size = (total + PARTS - 1) // PARTS

    for i in range(PARTS):
        part = deduped[i * chunk_size:(i + 1) * chunk_size]
        if not part:
            continue
        output = OUTPUT_DIR / f"products-{i + 1}.json"
        with output.open("w", encoding="utf-8") as f:
            json.dump(part, f, ensure_ascii=False, indent=2)
        # Re-open immediately so malformed JSON is caught before commit.
        with output.open("r", encoding="utf-8") as f:
            check = json.load(f)
        print(f"{output}: {len(check)} products")

    print(f"\nOriginal products: {len(products)}")
    print(f"Unique complete products: {total}")
    print(f"Created {min(PARTS, (total + chunk_size - 1) // chunk_size)} split files in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
