"""Registration of the Linear demo's backend package (see `app/installed_products.py`).

The package supplies two things the platform asks for by definition ID: a scope-bound record
lookup for one caller, and the temporary translator into today's action names (removed in 3.6).
Registration is code here, never a path named by a definition.
"""
from __future__ import annotations

from app.installed_products import ProductPackage
from products.linear_simplified.backend.lookup import lookup_for
from products.linear_simplified.backend.translator import translator_for

PACKAGE = ProductPackage(
    definition_id="linear_simplified",
    lookup_factory=lookup_for,
    legacy_translator=translator_for,
)
