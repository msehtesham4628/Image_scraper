import json
from pathlib import Path

INPUT = Path("products.json")
OUTPUT_DIR = Path("split_products")
PARTS = 4

with INPUT.open("r", encoding="utf-8") as f:
    products = json.load(f)

    if not isinstance(products, list):
        raise ValueError("products.json must contain a JSON array")

        OUTPUT_DIR.mkdir(exist_ok=True)

        total = len(products)
        chunk_size = (total + PARTS - 1) // PARTS

        for i in range(PARTS):
            start = i * chunk_size
                end = min(start + chunk_size, total)

                    part = products[start:end]

                        if not part:
                                continue

                                    output = OUTPUT_DIR / f"products-{i + 1}.json"

                                        with output.open("w", encoding="utf-8") as f:
                                                json.dump(part, f, ensure_ascii=False, indent=2)

                                                    print(f"{output}: {len(part)} products")

                                                    print(f"\nTotal products: {total}")
                                                    print(f"Created files in: {OUTPUT_DIR}")