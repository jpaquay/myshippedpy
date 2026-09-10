"""Firebase platform plumbing for Barogroove.

Everything in this package must import cleanly with an empty environment and
no credentials on disk. That is a hard rule, not an aspiration: the container
resolves these modules lazily and unit tests import them in a bare venv.

Consequences you must respect when editing anything here:

* No ``google.cloud.*`` / ``firebase_admin`` import at module top level. Import
  inside the function that needs it.
* No network at import time. No credential discovery at import time.
* Anything that can fail at runtime degrades: log, return an empty/None
  result, and let the caller carry on with reduced fidelity.

Modules
-------
``auth``       Firebase ID-token verification exposed as FastAPI dependencies.
``firestore``  Lazy async Firestore client factory + typed repositories.
``tokens``     Encrypted per-user provider-token vault (Fernet at rest).
"""

from __future__ import annotations

__all__ = ["auth", "firestore", "tokens"]
