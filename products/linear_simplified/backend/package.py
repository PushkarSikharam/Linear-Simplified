"""Registration of the Linear demo's backend package (see `app/installed_products.py`).

Its record lookup and temporary legacy translator arrive in 3.2 slice 3.
"""
from __future__ import annotations

from app.installed_products import ProductPackage

PACKAGE = ProductPackage(definition_id="linear_simplified")
