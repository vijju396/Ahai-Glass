"""Assemble the exact build context for the image, file by file.

`.dockerignore` was the obvious way to keep `node_modules`, the virtualenv and
the unscoped data out of the upload, and it does not work here: `az acr build`
packs the context with the Azure CLI's own archiver, and a listed
`frontend/node_modules/` still arrived with 15,956 entries in it. The context
measured 309 MB against a 68 MB bundle, which is how this was found (D-137).

So the context is built rather than filtered. Nothing is excluded, because
nothing is copied that should not be there — which is also the safer direction
for `backend/.env`: an ignore rule that silently stops working puts a live
OpenAI key in an image layer, and an allowlist cannot.

Run after `build_scoped_bundle.py` and before `az acr build`:

    python scripts/stage_build_context.py
    az acr build --registry acraisglassdemoci --image ais-glass-demo:v2 \
        --platform linux/amd64 --file Dockerfile deploy/context
"""

from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTEXT = PROJECT_ROOT / "deploy" / "context"

#: Copied whole. `deploy/bundle` is the scoped data; the rest is source.
TREES = (
    "backend/app",
    "backend/alembic",
    "backend/tests",
    "frontend/src",
    "frontend/public",
    "deploy/bundle",
)

FILES = (
    "backend/requirements.txt",
    "backend/pyproject.toml",
    "backend/alembic.ini",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    # Not backend/.env. `deploy/env.azure` is the same settings with the
    # OpenAI key removed, and the Dockerfile copies it to backend/.env inside
    # the image. The key reaches the container as a secret, never as a layer.
    "deploy/env.azure",
    "Dockerfile",
)

#: Dropped from the trees above: build output and caches that the image
#: rebuilds, and bytecode that would differ per machine.
PRUNE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}
PRUNE_SUFFIXES = {".pyc", ".pyo"}


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in PRUNE_DIRS or Path(name).suffix in PRUNE_SUFFIXES
    }


def _mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1_048_576
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1_048_576


def main() -> int:
    if CONTEXT.exists():
        shutil.rmtree(CONTEXT)
    CONTEXT.mkdir(parents=True)

    missing: list[str] = []
    for rel in TREES:
        src = PROJECT_ROOT / rel
        if not src.is_dir():
            missing.append(rel)
            continue
        shutil.copytree(src, CONTEXT / rel, ignore=_ignore)

    for rel in FILES:
        src = PROJECT_ROOT / rel
        if not src.is_file():
            missing.append(rel)
            continue
        (CONTEXT / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, CONTEXT / rel)

    if missing:
        print("MISSING — the build will fail without these:")
        for rel in missing:
            print(f"  {rel}")
        if "deploy/bundle" in missing:
            print("  run scripts/build_scoped_bundle.py first")
        if "deploy/env.azure" in missing:
            print("  run scripts/make_azure_env.py first")
        return 1

    # The one thing worth asserting rather than trusting: the key must not be
    # in the context under any name.
    strays = [p for p in CONTEXT.rglob(".env*") if p.name != ".env.example"]
    leaked = [p for p in strays if p.name == ".env"]
    if leaked:
        print(f"REFUSING: {[str(p) for p in leaked]} reached the context.")
        shutil.rmtree(CONTEXT)
        return 1

    for rel in (*TREES, "deploy/env.azure"):
        print(f"  {rel:<24} {_mb(CONTEXT / rel):>7.1f} MB")
    print(f"\ncontext  {_mb(CONTEXT):.1f} MB at {CONTEXT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
