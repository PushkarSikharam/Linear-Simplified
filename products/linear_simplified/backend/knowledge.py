"""This product's knowledge source (3.2 plan, section 7.2).

The platform asks for passages through `KnowledgeLookup`; this answers from today's product
document retriever. It exists so that dismantling the current assistant in slice 5 does not
silently empty `retrieved_context` — the documents a reply is grounded in keep coming from
somewhere real.

The lookup is bound to one product when it is built. `search` takes no product, tenant or scope,
so nothing a visitor says can widen what it reads. Real indexing, versioning and tenant-scoped
knowledge storage arrive in Milestone 3.4; this is the seam, not the implementation.
"""
from __future__ import annotations

from app.engine.knowledge import KnowledgeContext, KnowledgePassage
from app.services.retriever import ProductRetriever


class LinearKnowledgeLookup:
    """Read-only passages for one caller, from the documents this product ships.

    Built for one `KnowledgeContext` and never told about another: the organization, the product
    deployment, the pinned definition version and checksum, and the caller's knowledge scope are
    all fixed here. `search` takes only a question.

    Today's documents are static and shipped with the definition, so retrieval is keyed by the
    definition ID and the rest of the context is carried without changing what is read. That is a
    property of *this* implementation, not of the boundary: when Milestone 3.4 stores knowledge
    per tenant and per version, this class changes and the platform does not.
    """

    def __init__(self, context: KnowledgeContext, retriever: ProductRetriever | None = None) -> None:
        self._context = context
        self._retriever = retriever or ProductRetriever()

    @property
    def context(self) -> KnowledgeContext:
        return self._context

    def search(self, text: str, limit: int) -> list[KnowledgePassage]:
        if not text.strip() or limit <= 0:
            return []
        documents = self._retriever.retrieve(self._context.definition_id, text, limit=limit)
        return [
            KnowledgePassage(title=document.title, source=document.source, snippet=document.snippet)
            for document in documents
        ]


def knowledge_for(context: KnowledgeContext) -> LinearKnowledgeLookup:
    """Bind a knowledge lookup to one caller's context. Nothing widens it afterwards."""
    return LinearKnowledgeLookup(context)
