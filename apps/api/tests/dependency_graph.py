"""Static import graph for the engine dependency boundary.

Imports are read with `ast` (nothing is executed) and followed transitively through modules
of the scanned package. Dynamic imports cannot be followed, so they are reported separately
and banned where the boundary applies.
"""
from __future__ import annotations

import ast
from collections import deque
from pathlib import Path


def module_path(root: Path, module: str) -> Path | None:
    """The source file for `module` under `root` (the directory containing the top package)."""
    base = root.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def imported_modules(path: Path, module: str) -> set[str]:
    """Every module named by an import statement, including imports inside functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parent = parts[: len(parts) - (node.level - 1)]
                base = ".".join([*parent, base] if base else parent)
            names.add(base)
            # `from pkg import sub` may name a submodule.
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def dynamic_imports(path: Path) -> list[str]:
    """Calls that import by computed name, which a static graph cannot follow."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                found.append(f"{path.name}:{node.lineno} __import__")
            if isinstance(func, ast.Attribute) and func.attr == "import_module":
                found.append(f"{path.name}:{node.lineno} import_module")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = [alias.name for alias in node.names] + [getattr(node, "module", None) or ""]
            if any(name == "importlib" or name.startswith("importlib.") for name in imported):
                found.append(f"{path.name}:{node.lineno} importlib")
    return found


def package_modules(root: Path, package: str) -> list[str]:
    """Every module of `package`, including those in subpackages."""
    base = root.joinpath(*package.split("."))
    modules = []
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(".".join(parts))
    return modules


def parent_packages(module: str) -> list[str]:
    """Packages whose `__init__.py` runs before `module` is imported, outermost first."""
    parts = module.split(".")
    return [".".join(parts[:index]) for index in range(1, len(parts))]


def reachable(root: Path, starts: list[str], scanned_prefix: str, stop_at: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    """Map every module reachable from `starts` to the import chain that reaches it.

    Modules under `scanned_prefix` are followed; anything else is recorded but not opened.
    Modules in `stop_at` are recorded but not followed (registry entry points).
    Importing a module also runs every parent package's `__init__.py`, so those are followed too.
    """
    chains: dict[str, list[str]] = {}
    queue: deque[str] = deque()

    def add(name: str, chain: list[str]) -> None:
        for parent in parent_packages(name):
            if parent not in chains:
                chains[parent] = [*chain, parent]
                queue.append(parent)
        if name not in chains:
            chains[name] = [*chain, name]
            queue.append(name)

    for start in starts:
        add(start, [])
    while queue:
        current = queue.popleft()
        if current in stop_at or not (current == scanned_prefix or current.startswith(scanned_prefix + ".")):
            continue
        path = module_path(root, current)
        if path is None:
            continue
        for name in sorted(imported_modules(path, current)):
            in_scanned = name == scanned_prefix or name.startswith(scanned_prefix + ".")
            if in_scanned and module_path(root, name) is None:
                continue  # an imported name, not a module
            if name:
                add(name, chains[current])
    return chains


def forbidden_hits(chains: dict[str, list[str]], forbidden: tuple[str, ...]) -> dict[str, list[str]]:
    return {
        module: chain for module, chain in chains.items()
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
    }
