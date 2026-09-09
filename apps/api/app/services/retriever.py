from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.product_config import PRODUCTS_BY_ID
from app.services.language_normalizer import normalize_for_intent


@dataclass(frozen=True)
class RetrievedDocument:
    title: str
    source: str
    snippet: str
    score: int


ROOT_DIR = Path(__file__).resolve().parents[4]

FEATURE_KEYWORDS = {
    "cycles": {"cycle", "cycles", "sprint", "planning", "burndown", "time-boxed"},
    "issues": {"issue", "issues", "bug", "bugs", "ticket", "tickets", "triage", "assign", "assignee"},
    "projects": {"project", "projects", "roadmap", "initiative", "initiatives", "progress"},
    "teams": {"team", "teams", "capacity", "workload", "owner", "ownership", "people"},
    "integrations": {"integration", "integrations", "github", "slack", "jira", "import", "migration"},
}


class ProductRetriever:
    def retrieve(self, product_id: str, query: str, limit: int = 2) -> list[RetrievedDocument]:
        product = PRODUCTS_BY_ID.get(product_id)
        if product is None:
            return []

        docs_dir = (ROOT_DIR / product.docs_path).resolve()
        root_dir = ROOT_DIR.resolve()
        if root_dir not in docs_dir.parents and docs_dir != root_dir:
            return []

        query_terms = self._query_terms(query)
        scored_docs: list[RetrievedDocument] = []

        for doc_path in sorted(docs_dir.glob("*.md")):
            document = self._load_doc(doc_path)
            score = self._score(document.source, document.title, document.snippet, query_terms)
            if score > 0:
                scored_docs.append(
                    RetrievedDocument(
                        title=document.title,
                        source=document.source,
                        snippet=document.snippet,
                        score=score,
                    )
                )

        scored_docs.sort(key=lambda document: (-document.score, document.source))
        return scored_docs[:limit]

    def _query_terms(self, query: str) -> set[str]:
        terms = set(re.findall(r"[a-z0-9-]+", normalize_for_intent(query)))
        expanded = set(terms)
        if {"week", "weekly", "week-by-week"} & terms and {"plan", "planning", "work", "focus"} & terms:
            expanded.add("__cycles_intent__")
            expanded.add("cycles")
            expanded.update(FEATURE_KEYWORDS["cycles"])
        for feature, keywords in FEATURE_KEYWORDS.items():
            if terms & keywords:
                expanded.add(feature)
                expanded.update(keywords)
        return expanded

    def _score(self, source: str, title: str, snippet: str, query_terms: set[str]) -> int:
        doc_terms = set(re.findall(r"[a-z0-9-]+", f"{source} {title} {snippet}".lower()))
        score = len(query_terms & doc_terms)
        for feature in FEATURE_KEYWORDS:
            if feature in query_terms and source.startswith(feature):
                score += 3
        if "__cycles_intent__" in query_terms and source.startswith("cycles"):
            score += 8
        return score

    @lru_cache(maxsize=32)
    def _load_doc(self, doc_path: Path) -> RetrievedDocument:
        content = doc_path.read_text(encoding="utf-8")
        title = self._title(content, doc_path)
        snippet = self._snippet(content)
        return RetrievedDocument(
            title=title,
            source=doc_path.name,
            snippet=snippet,
            score=0,
        )

    def _title(self, content: str, doc_path: Path) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line.removeprefix("# ").strip()
        return doc_path.stem.title()

    def _snippet(self, content: str) -> str:
        paragraphs = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        return " ".join(paragraphs[:2])
