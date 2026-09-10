"""BAROGROOVE — entry point.

    uvicorn app:app --reload

This file is the last survivor of the hello-world repo this project grew out
of. It used to read, more or less:

    from fastapi import Fastapi          # <- wrong case; never imported
    app = Fastapi(__name__)              # <- Flask's constructor signature
    @app.route("/")                      # <- Flask's decorator
    def hello():
        return "Hello World!!"

Four bugs in five lines. The typo'd class name, the Flask ``__name__``
argument, the Flask ``@app.route`` decorator on a FastAPI object, and a sync
handler where the framework wanted an async one.

All four are fixed. The string survives, at ``GET /legacy``.

Everything real lives under ``backend/app``. This module stays a thin,
boring shim on purpose: Cloud Run's start command, the Dockerfile and every
tutorial-shaped muscle memory all point at ``app:app``, and there is no value
in surprising them.
"""

from __future__ import annotations

from backend.app.main import create_app

#: The ASGI application. ``uvicorn app:app`` and the container CMD both want this.
app = create_app()


if __name__ == "__main__":  # pragma: no cover - convenience for local runs
    import os

    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("BG_ENVIRONMENT", "local") == "local",
    )
