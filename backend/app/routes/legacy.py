"""The easter egg.

This repository began life as a hello-world. Four files, a `Fastapi` typo, a
Dockerfile pointing at scripts that were never committed, and a requirements
file that listed `buildpack` as if it were a Python package.

Everything else has been rewritten. This endpoint has not. It is the original
string, preserved exactly, because a codebase should remember where it came
from.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["legacy"])

#: Do not "fix" the exclamation marks. They are load-bearing.
HELLO = "Hello World!!"


@router.get("/legacy", response_class=PlainTextResponse, summary="Where this all started")
async def legacy() -> str:
    """Return the original hello-world payload, byte for byte."""
    return HELLO


@router.get("/legacy/about", summary="Provenance of the easter egg")
async def legacy_about() -> dict[str, object]:
    return {
        "message": HELLO,
        "origin": "the four-file hello-world this repo grew out of",
        "inherited": ["app.py", "CNAME"],
        "fixed": [
            "app.py declared `Fastapi()` — wrong case, and then used Flask idioms on it",
            "Dockerfile invoked .shipped/ scripts that were never committed",
            "requirements.txt listed `buildpack`, which is not a Python package",
        ],
        "kept_because": "lineage is cheap to keep and expensive to fake",
    }
