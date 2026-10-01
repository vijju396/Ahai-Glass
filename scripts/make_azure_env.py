"""Regenerate `deploy/env.azure` from `backend/.env`, minus the OpenAI key.

The deployed image carries the project's real settings — same workspace, same
grain, same eligibility profile, same accuracy constants — because a deployment
that silently fell back to code defaults would be reporting on a different
slice than the one these docs describe. What it must not carry is the key:
anything copied into an image stays in that image's layers, so the key is
injected at run time as a Container Apps secret instead (D-136).

Run after any change to `backend/.env`:

    python scripts/make_azure_env.py
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "backend" / ".env"
TARGET = PROJECT_ROOT / "deploy" / "env.azure"

#: Both spellings the settings layer accepts for the key.
SECRET_NAMES = ("OPENAI_API_KEY", "AIS_OPENAI_API_KEY")

HEADER = """\
# Generated from backend/.env for the Azure image — do not edit by hand.
# Regenerate with scripts/make_azure_env.py after changing backend/.env.
#
# Identical to the local settings except for the OpenAI key, so the
# deployment reports on the same workspace, at the same grain, with the
# same eligibility profile and the same accuracy settings. A deployment
# that quietly fell back to code defaults would be a different application.
"""

PLACEHOLDER = """\
# OPENAI_API_KEY is deliberately absent. It is injected at run time as a
# Container Apps secret, so it exists in no image layer."""


def main() -> int:
    if not SOURCE.is_file():
        print(f"{SOURCE} not found — nothing to generate from.")
        return 1

    out: list[str] = []
    dropped: list[str] = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        name = line.strip().split("=", 1)[0].strip()
        if "=" in line and name in SECRET_NAMES:
            dropped.append(name)
            out.append(PLACEHOLDER)
            continue
        out.append(line)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(HEADER + "\n".join(out) + "\n", encoding="utf-8")
    # Names only. The point of this script is that the value is never printed.
    print(f"wrote {TARGET.relative_to(PROJECT_ROOT)} — withheld {dropped or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
