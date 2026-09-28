"""Approved product-wide text, with immutable versions and no external URL fetching."""
from __future__ import annotations

import hashlib
import json
import math
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthUser, require_member
from app.db import get_connection
from app.definitions.access import AccessDenied, authorize_product
from app.definitions.organizations import OrganizationDirectory
from app.engine.knowledge import KnowledgeContext, KnowledgePassage
from collections.abc import Mapping

router = APIRouter(prefix="/api/products", tags=["knowledge"])


class ApprovedText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=32000)
    approved: bool


def _access(user: AuthUser, product_id: str):
    try:
        return authorize_product(user, product_id, OrganizationDirectory())
    except AccessDenied:
        raise HTTPException(404, "This product is not available.") from None


@router.get("/{product_id}/knowledge")
def documents(product_id: str, user: AuthUser = Depends(require_member)) -> dict:
    access = _access(user, product_id)
    with get_connection() as connection:
        rows = connection.execute(
            "select document_id, title, length(body) as characters from approved_documents "
            "where tenant_id=? and product_id=? and knowledge_version=? and definition_checksum=? order by title",
            (user.tenant_id, product_id, access.binding.knowledge_version, access.binding.definition_checksum),
        ).fetchall()
    return {"version": access.binding.knowledge_version, "documents": [dict(row) for row in rows]}


class KnowledgeFull(Exception):
    """This product has as much approved text as it may hold."""


def store_document(connection, tenant_id: str, product_id: str, definition_checksum: str,
                   knowledge_version: int, title: str, body: str) -> tuple[int, str]:
    """Add one approved document to a product, as a new knowledge version.

    A version is written whole rather than appended to, so the set of documents at any version is
    exactly what was approved together, and a session pinned to a version keeps reading what it
    started with. Shared so that text somebody approves on the knowledge screen and text they
    wrote when they added the product are stored on identical terms - there is no second kind of
    approved text with rules of its own.
    """
    rows = connection.execute(
        "select document_id, title, body from approved_documents "
        "where tenant_id=? and product_id=? and knowledge_version=? and definition_checksum=?",
        (tenant_id, product_id, knowledge_version, definition_checksum)).fetchall()
    if len(rows) >= 16 or sum(len(row["body"]) for row in rows) + len(body) > 128000 or knowledge_version >= 21:
        raise KnowledgeFull
    document_id = uuid4().hex
    content = [dict(row) for row in rows] + [
        {"document_id": document_id, "title": title.strip(), "body": body.strip()}]
    checksum = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    for item in content:
        connection.execute("insert into approved_documents values (?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, product_id, definition_checksum, knowledge_version + 1,
                            item["document_id"], item["title"], item["body"]))
    connection.execute(
        "update product_bindings set knowledge_version=?, knowledge_checksum=? "
        "where tenant_id=? and product_id=?",
        (knowledge_version + 1, checksum, tenant_id, product_id))
    return knowledge_version + 1, document_id


@router.post("/{product_id}/knowledge", status_code=201)
def approve_document(product_id: str, body: ApprovedText, user: AuthUser = Depends(require_member)) -> dict:
    if not body.approved or not body.title.strip() or not body.text.strip():
        raise HTTPException(422, "Approve non-empty source text before publishing.")
    with get_connection() as connection:
        connection.execute("begin immediate")
        directory = OrganizationDirectory(connection=connection)
        membership = directory.membership(user.tenant_id, user.user_id)
        try:
            access = authorize_product(user, product_id, directory)
        except AccessDenied:
            raise HTTPException(404, "This product is not available.") from None
        if membership is None or not (membership.role == "org_admin" or
                                      (membership.role == "team_admin" and membership.team_id == access.binding.team_id)):
            raise HTTPException(403, "Only this product's administrators can publish source text.")
        try:
            version, document_id = store_document(
                connection, user.tenant_id, product_id, access.binding.definition_checksum,
                access.binding.knowledge_version, body.title, body.text)
        except KnowledgeFull:
            raise HTTPException(409, "This product's source capacity is reached.") from None
    return {"version": version, "document_id": document_id}


# Words that say how a question is asked rather than what it is about. They match every
# document, so counting them would rank on question length instead of on subject.
_ASKING_WORDS = frozenset({
    "the", "and", "for", "with", "what", "whats", "how", "why", "who", "when", "where", "which",
    "does", "did", "can", "could", "would", "should", "will", "you", "your", "our", "its",
    "about", "this", "that", "these", "those", "are", "was", "were", "have", "has", "had",
    "please", "tell", "explain", "there", "here", "any", "some", "into", "from", "just",
})
# A passage is quoted as an answer only when it is really about the question: two subject words
# in common, or one that the document is titled after. One incidental word in common is how a
# reader gets told about adding a product when they asked about something else entirely.
MIN_MATCHED_TERMS = 2
_TITLE_WEIGHT = 3.0


def _subject_terms(text: str) -> set[str]:
    """What a question is about, with plural and tense endings removed so they can match."""
    return {_stem(word) for word in re.findall(r"\w{3,}", text.casefold())
            if word not in _ASKING_WORDS}


def _title_fit(text: str, title: str) -> int:
    """How many of the question's own words, asking words included, a document's title uses.

    Only ever a tie-break. "What is Pixel?" asks about nothing but Pixel, which "What Pixel is"
    and "How Pixel works" both name; the question's shape is what says which one it wants.
    """
    asked = {_stem(word) for word in re.findall(r"\w{2,}", text.casefold())}
    return len(asked & {_stem(word) for word in re.findall(r"\w{2,}", title.casefold())})


def _stem(word: str) -> str:
    """A crude common-ending trim, so records matches record and lasts matches last.

    Deliberately small and predictable rather than a real stemmer: a reply is quoted from the
    document itself, so the only job here is to stop an ending difference hiding a match.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    # A silent final e last of all, so change, changes and changed all end up the same. Trimming
    # it only from some of them is how a word stops matching itself.
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


class ApprovedKnowledge:
    """This product's approved text, for one organization at one pinned version.

    Ranking is plain and local: a word shared with fewer documents counts for more than one every
    document uses, and a word in a document's title counts for more than one buried in its body.
    Nothing is fetched, no model is consulted, and a question can only ever reach the rows the
    context was built with.
    """

    def __init__(self, context: KnowledgeContext):
        self.context = context

    def documents(self) -> list[Mapping[str, str]]:
        """The approved text this product may be answered from, at its pinned version.

        A seam, not a convenience: a product whose text is partly derived from what the platform
        already knows - Pixel's own console, which can say what each of your products is for -
        adds it here and is then ranked by exactly the same rule as text somebody typed. The
        alternative, a second search with a second ranking, is how two answers to one question
        start disagreeing.
        """
        context = self.context
        with get_connection() as connection:
            rows = connection.execute("select document_id, title, body from approved_documents "
                                      "where tenant_id=? and product_id=? and knowledge_version=? and definition_checksum=?",
                                      (context.tenant_id, context.product_id, context.knowledge_version, context.definition_checksum)).fetchall()
        return [{"document_id": row["document_id"], "title": row["title"], "body": row["body"]}
                for row in rows]

    def search(self, text: str, limit: int = 3) -> list[KnowledgePassage]:
        terms = _subject_terms(text)
        if not terms:
            return []
        rows = self.documents()
        chunks = [(row, start, row["body"][start:start + 1000])
                  for row in rows for start in range(0, len(row["body"]), 900)]
        # How many passages use each word, so that a word common to all of them cannot decide
        # which one is the answer. Never zero, so a word every document shares still counts.
        appearances: dict[str, int] = {}
        for _, _, snippet in chunks:
            for term in {_stem(word) for word in re.findall(r"\w{3,}", snippet.casefold())}:
                appearances[term] = appearances.get(term, 0) + 1
        total = max(len(chunks), 1)
        ranked = []
        for row, start, snippet in chunks:
            title_terms = {_stem(word) for word in re.findall(r"\w{3,}", row["title"].casefold())}
            body_terms = {_stem(word) for word in re.findall(r"\w{3,}", snippet.casefold())}
            matched = terms & (title_terms | body_terms)
            if not matched:
                continue
            score = sum(
                (1.0 + math.log((total + 1) / (appearances.get(term, 0) + 1)))
                * (_TITLE_WEIGHT if term in title_terms else 1.0)
                for term in matched
            )
            grounds = len(matched) >= MIN_MATCHED_TERMS or bool(matched & title_terms)
            ranked.append((score, _title_fit(text, row["title"]), row["document_id"], start, KnowledgePassage(
                title=row["title"], source=f"document:{row['document_id']}",
                snippet=snippet, grounds_answer=grounds)))
        # Ties go to the title that reads most like the question, then to document and position, so
        # the same question always reads the same way.
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
        return [passage for _, _, _, _, passage in ranked[:max(0, min(limit, 5))]]
