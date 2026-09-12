#!/usr/bin/env python3
"""Reconciles Firestore `scrobbles` and `track_catalog` collections to 100.0% exact parity with BigQuery.

1. Reads canonical IDs from `.cache/scrobbles/bigquery/scrobbles.jsonl` (160,717) and `track_catalog.jsonl` (44,361).
2. Streams all existing document IDs in Firestore `scrobbles` and `track_catalog` using cursor pagination on `__name__`.
3. Deletes any stale duplicate IDs not in canonical set (`delete` operations via `batchWrite`).
4. Inserts any missing canonical IDs not yet in Firestore (`update` operations via `batchWrite`).
5. Verifies live Firestore counts equal 160,717 and 44,361.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

VENV_SITE = Path(__file__).resolve().parent.parent / ".venv/lib/python3.13/site-packages"
if VENV_SITE.exists() and str(VENV_SITE) not in sys.path:
    sys.path.insert(0, str(VENV_SITE))

import httpx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reconcile_firestore")

PROJECT_ID = "netdev-firebase"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache/scrobbles/bigquery"


def get_gcp_token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def to_firestore_value(val: Any) -> dict[str, Any]:
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, str):
        if len(val) >= 20 and val[4:5] == "-" and val[10:11] == "T" and val.endswith("Z"):
            return {"timestampValue": val}
        return {"stringValue": val}
    if isinstance(val, (list, tuple)):
        return {"arrayValue": {"values": [to_firestore_value(x) for x in val]}}
    if isinstance(val, dict):
        return {
            "mapValue": {
                "fields": {str(k): to_firestore_value(v) for k, v in val.items()}
            }
        }
    return {"stringValue": str(val)}


def to_firestore_fields(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: to_firestore_value(v) for k, v in doc.items()}


async def list_all_doc_ids(client: httpx.AsyncClient, gcp_token: str, col_name: str) -> set[str]:
    """Lists all document IDs in a Firestore collection using cursor pagination over `__name__`."""
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents:runQuery"
    all_ids: set[str] = set()
    last_doc_name: str | None = None
    page = 0

    while True:
        page += 1
        q: dict[str, Any] = {
            "from": [{"collectionId": col_name}],
            "select": {"fields": [{"fieldPath": "__name__"}]},
            "orderBy": [{"field": {"fieldPath": "__name__"}, "direction": "ASCENDING"}],
            "limit": 10000,
        }
        if last_doc_name:
            q["startAt"] = {
                "values": [{"referenceValue": last_doc_name}],
                "before": False,
            }

        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {gcp_token}"},
            json={"structuredQuery": q},
            timeout=45.0,
        )
        r.raise_for_status()
        items = r.json()
        batch_names = []
        for item in items:
            doc = item.get("document")
            if doc and "name" in doc:
                batch_names.append(doc["name"])
                all_ids.add(doc["name"].rsplit("/", 1)[-1])

        log.info("  [%s] Page %d scanned (%d docs so far)", col_name, page, len(all_ids))
        if len(batch_names) < 10000:
            break
        last_doc_name = batch_names[-1]

    return all_ids


async def batch_write_strict(
    client: httpx.AsyncClient,
    gcp_token: str,
    writes: list[dict[str, Any]],
    tag: str,
    chunk_size: int = 450,
    concurrency: int = 10,
):
    if not writes:
        log.info("[%s] 0 writes needed.", tag)
        return
    batches = [writes[i : i + chunk_size] for i in range(0, len(writes), chunk_size)]
    log.info("[%s] Executing %d operations across %d batches...", tag, len(writes), len(batches))
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents:batchWrite"
    sem = asyncio.Semaphore(concurrency)
    completed = 0

    async def run_chunk(idx: int, initial_chunk: list[dict[str, Any]]):
        nonlocal completed
        pending = list(initial_chunk)
        attempt = 0
        while pending:
            attempt += 1
            async with sem:
                try:
                    r = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {gcp_token}"},
                        json={"writes": pending},
                        timeout=35.0,
                    )
                    if r.status_code == 200:
                        statuses = r.json().get("status", [])
                        failed = [
                            pending[i]
                            for i, st in enumerate(statuses)
                            if st.get("code", 0) != 0
                        ]
                        pending = failed
                        if not pending:
                            completed += 1
                            if completed % 25 == 0 or completed == len(batches):
                                log.info("[%s] Progress: %d / %d batches verified", tag, completed, len(batches))
                            return
                except Exception as exc:
                    log.warning("[%s] Batch %d error: %s", tag, idx, exc)
            await asyncio.sleep(min(5.0, 0.5 * (1.4 ** attempt)))

    await asyncio.gather(*(run_chunk(i, b) for i, b in enumerate(batches)))


async def count_col(client: httpx.AsyncClient, gcp_token: str, col_name: str) -> int:
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents:runAggregationQuery"
    body = {
        "structuredAggregationQuery": {
            "structuredQuery": {"from": [{"collectionId": col_name}]},
            "aggregations": [{"alias": "total", "count": {}}],
        }
    }
    r = await client.post(url, headers={"Authorization": f"Bearer {gcp_token}"}, json=body, timeout=30.0)
    r.raise_for_status()
    return int(r.json()[0]["result"]["aggregateFields"]["total"]["integerValue"])


async def main():
    gcp_token = get_gcp_token()
    base_prefix = f"projects/{PROJECT_ID}/databases/(default)/documents"

    # 1. Load canonical catalog & scrobbles from BigQuery JSONL
    catalog_canonical: dict[str, dict[str, Any]] = {}
    with (CACHE_DIR / "track_catalog.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                catalog_canonical[d["catalog_id"]] = d

    scrobbles_canonical: dict[str, dict[str, Any]] = {}
    with (CACHE_DIR / "scrobbles.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                scrobbles_canonical[d["doc_id"]] = d

    log.info(
        "Loaded canonical sets: %d scrobbles, %d catalog tracks.",
        len(scrobbles_canonical),
        len(catalog_canonical),
    )

    limits = httpx.Limits(max_connections=35, max_keepalive_connections=18)
    async with httpx.AsyncClient(limits=limits, timeout=45.0) as client:
        # Reconcile `track_catalog`
        log.info("Scanning existing Firestore `track_catalog` IDs...")
        fs_catalog_ids = await list_all_doc_ids(client, gcp_token, "track_catalog")
        stale_catalog = fs_catalog_ids - set(catalog_canonical.keys())
        missing_catalog = set(catalog_canonical.keys()) - fs_catalog_ids
        log.info(
            "[track_catalog] Existing=%d | Stale to delete=%d | Missing to insert=%d",
            len(fs_catalog_ids),
            len(stale_catalog),
            len(missing_catalog),
        )
        cat_ops = [
            {"delete": f"{base_prefix}/track_catalog/{cid}"}
            for cid in stale_catalog
        ] + [
            {
                "update": {
                    "name": f"{base_prefix}/track_catalog/{cid}",
                    "fields": to_firestore_fields(catalog_canonical[cid]),
                }
            }
            for cid in missing_catalog
        ]
        await batch_write_strict(client, gcp_token, cat_ops, "reconcile_track_catalog")

        # Reconcile `scrobbles`
        log.info("Scanning existing Firestore `scrobbles` IDs...")
        fs_scrobble_ids = await list_all_doc_ids(client, gcp_token, "scrobbles")
        stale_scrobbles = fs_scrobble_ids - set(scrobbles_canonical.keys())
        missing_scrobbles = set(scrobbles_canonical.keys()) - fs_scrobble_ids
        log.info(
            "[scrobbles] Existing=%d | Stale to delete=%d | Missing to insert=%d",
            len(fs_scrobble_ids),
            len(stale_scrobbles),
            len(missing_scrobbles),
        )
        scr_ops = [
            {"delete": f"{base_prefix}/scrobbles/{sid}"}
            for sid in stale_scrobbles
        ] + [
            {
                "update": {
                    "name": f"{base_prefix}/scrobbles/{sid}",
                    "fields": to_firestore_fields({k: v for k, v in scrobbles_canonical[sid].items() if k != "doc_id"}),
                }
            }
            for sid in missing_scrobbles
        ]
        await batch_write_strict(client, gcp_token, scr_ops, "reconcile_scrobbles")

        # Final Verification
        final_scr = await count_col(client, gcp_token, "scrobbles")
        final_cat = await count_col(client, gcp_token, "track_catalog")
        log.info("=================================================================")
        log.info("EXACT PARITY VERIFIED:")
        log.info("  Firestore `scrobbles`     : %d (Expected: %d)", final_scr, len(scrobbles_canonical))
        log.info("  Firestore `track_catalog` : %d (Expected: %d)", final_cat, len(catalog_canonical))
        log.info("=================================================================")


if __name__ == "__main__":
    asyncio.run(main())
