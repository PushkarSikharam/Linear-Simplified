"""Finds product-specific vocabulary in Pixel core source files.

Core is everything under `apps/api/app` and the web app's `app`, `lib` and `types`
directories. Product packages (`products/`) and web adapter packages (`apps/web/adapters/`)
are where product-specific names belong.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

CORE_ROOTS = (
    ("apps/api/app", ("*.py",)),
    ("apps/web/app", ("*.ts", "*.tsx")),
    ("apps/web/lib", ("*.ts", "*.tsx")),
    ("apps/web/types", ("*.ts", "*.tsx")),
)

# Names and concepts that belong to a specific product definition, never to core.
PRODUCT_TERMS = re.compile(
    r"\b(?:issues?|tickets?|cycles?|sprints?|projects?|assignees?|linear|jira|github|slack|"
    r"salesforce|gmail|edith|maya|noah|avery|iris|sam rivera|lin-\d+|pix-\d+|prj-\d+|cyc-\d+)\b",
    re.IGNORECASE,
)


def product_ids() -> list[str]:
    products = REPO_ROOT / "products"
    return sorted(path.name for path in products.iterdir() if (path / "definition").is_dir())


def core_files() -> list[Path]:
    files: list[Path] = []
    for root, patterns in CORE_ROOTS:
        for pattern in patterns:
            files.extend(
                path for path in (REPO_ROOT / root).rglob(pattern)
                if ".test." not in path.name and "__pycache__" not in path.parts
            )
    return sorted(set(files))


def product_term_hits(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    ids = sum(len(re.findall(rf"\b{re.escape(product_id)}\b", text)) for product_id in product_ids())
    return len(PRODUCT_TERMS.findall(text)) + ids


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


if __name__ == "__main__":
    for path in core_files():
        hits = product_term_hits(path)
        if hits:
            print(f"{hits:5}  {relative(path)}")
