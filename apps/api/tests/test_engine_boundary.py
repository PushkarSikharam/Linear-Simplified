"""Milestone 3.2: the generic engine must not depend on product-specific code, even indirectly."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dependency_graph import dynamic_imports, forbidden_hits, package_modules, reachable

API_ROOT = Path(__file__).resolve().parents[1]
ENGINE = API_ROOT / "app" / "engine"

# Product-specific or legacy modules the engine may never reach.
FORBIDDEN = (
    "app.services.demo_data",
    "app.services.product_data_store",
    "app.workspace_config",
    "app.product_config",
    "products",
)
# The registry entry point is the only core module allowed to import product packages.
REGISTRY = frozenset({"app.installed_products"})


def engine_modules() -> list[str]:
    return package_modules(API_ROOT, "app.engine")


class EngineBoundaryTest(unittest.TestCase):
    def test_engine_modules_exist(self):
        self.assertIn("app.engine.actions", engine_modules())

    def test_engine_never_reaches_product_specific_modules(self):
        chains = reachable(API_ROOT, engine_modules(), "app", stop_at=REGISTRY)
        hits = forbidden_hits(chains, FORBIDDEN)
        self.assertEqual(
            {module: " -> ".join(chain) for module, chain in hits.items()}, {},
            "the engine depends on product-specific code",
        )

    def test_engine_has_no_dynamic_imports(self):
        found = [hit for path in sorted(ENGINE.rglob("*.py")) for hit in dynamic_imports(path)]
        self.assertEqual(found, [])

    def test_engine_direct_dependencies_are_listed_for_review(self):
        # Printed so each pull request shows what the engine depends on directly.
        chains = reachable(API_ROOT, engine_modules(), "app", stop_at=REGISTRY)
        direct = sorted(module for module, chain in chains.items() if len(chain) == 2 and module.startswith("app."))
        print("\nengine direct app dependencies:", ", ".join(direct))
        self.assertTrue(all(not module.startswith("products") for module in direct))


class DependencyGraphSelfTest(unittest.TestCase):
    """The checker itself must catch what a direct-import check would miss."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, relative: str, source: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")

    def test_a_neutral_helper_importing_product_code_is_caught(self):
        self.write("app/__init__.py", "")
        self.write("app/engine/__init__.py", "")
        self.write("app/engine/router.py", "from app.helpers import words\n")
        self.write("app/helpers.py", "def words():\n    from app.legacy_data import rows\n    return rows\n")
        self.write("app/legacy_data.py", "rows = []\n")
        chains = reachable(self.root, ["app.engine.router"], "app")
        hits = forbidden_hits(chains, ("app.legacy_data",))
        self.assertEqual(hits["app.legacy_data"], ["app.engine.router", "app.helpers", "app.legacy_data"])

    def test_package_initialization_is_followed(self):
        # Importing app.helpers.safe runs app/helpers/__init__.py first.
        self.write("app/__init__.py", "")
        self.write("app/engine/__init__.py", "")
        self.write("app/engine/router.py", "from app.helpers.safe import words\n")
        self.write("app/helpers/__init__.py", "from app.legacy_data import rows\n")
        self.write("app/helpers/safe.py", "def words():\n    return []\n")
        self.write("app/legacy_data.py", "rows = []\n")
        chains = reachable(self.root, ["app.engine.router"], "app")
        hits = forbidden_hits(chains, ("app.legacy_data",))
        self.assertEqual(hits["app.legacy_data"][-2:], ["app.helpers", "app.legacy_data"])

    def test_the_start_modules_own_packages_are_followed(self):
        self.write("app/__init__.py", "import products.demo\n")
        self.write("app/engine/__init__.py", "")
        self.write("app/engine/router.py", "")
        chains = reachable(self.root, ["app.engine.router"], "app")
        self.assertIn("products.demo", forbidden_hits(chains, ("products",)))

    def test_engine_subpackages_are_scanned(self):
        self.write("app/__init__.py", "")
        self.write("app/engine/__init__.py", "")
        self.write("app/engine/routing/__init__.py", "")
        self.write("app/engine/routing/stages.py", "from app.legacy_data import rows\n")
        self.write("app/legacy_data.py", "rows = []\n")
        modules = package_modules(self.root, "app.engine")
        self.assertEqual(modules, ["app.engine", "app.engine.routing", "app.engine.routing.stages"])
        chains = reachable(self.root, modules, "app")
        self.assertIn("app.legacy_data", forbidden_hits(chains, ("app.legacy_data",)))

    def test_relative_imports_are_resolved(self):
        self.write("app/__init__.py", "")
        self.write("app/engine/__init__.py", "")
        self.write("app/engine/a.py", "from . import b\nfrom ..legacy_data import rows\n")
        self.write("app/engine/b.py", "")
        self.write("app/legacy_data.py", "rows = []\n")
        chains = reachable(self.root, ["app.engine.a"], "app")
        self.assertIn("app.engine.b", chains)
        self.assertIn("app.legacy_data", forbidden_hits(chains, ("app.legacy_data",)))

    def test_registry_entry_points_are_not_followed(self):
        self.write("app/__init__.py", "")
        self.write("app/engine/__init__.py", "")
        self.write("app/engine/a.py", "from app.registry import find\n")
        self.write("app/registry.py", "def find():\n    from products.demo import thing\n")
        chains = reachable(self.root, ["app.engine.a"], "app", stop_at=frozenset({"app.registry"}))
        self.assertEqual(forbidden_hits(chains, ("products",)), {})
        chains = reachable(self.root, ["app.engine.a"], "app")
        self.assertIn("products.demo", forbidden_hits(chains, ("products",)))

    def test_dynamic_imports_are_reported(self):
        self.write("mod.py", "import importlib\nx = importlib.import_module('products.demo')\ny = __import__('os')\n")
        found = dynamic_imports(self.root / "mod.py")
        self.assertEqual(len(found), 3)


if __name__ == "__main__":
    unittest.main()
