"""
Experiment: async orchestration.

Problem this stands in for: the real Dependency Mapper will need to read and
parse potentially hundreds of files from a target repo. Doing that one file
at a time is wasted time — disk/IO reads spend most of their time waiting,
not computing. This script solves a smaller version of the same problem:
fetch N "documents" concurrently, some slow and some fast, some that fail,
and get all the results back without one slow/failed item blocking the rest.
"""

import asyncio
import random


async def fetch_one(doc_id: int) -> dict:
    """
    Simulates one IO-bound unit of work (a file read, an HTTP call, a DB
    query — in the real system, reading + doing a first pass over one
    source file). The sleep stands in for "waiting on IO," which is exactly
    the kind of wait async is designed to overlap with other work.
    """
    delay = random.uniform(0.05, 0.4)
    await asyncio.sleep(delay)

    if doc_id == 4:
        raise ValueError(f"doc {doc_id} is corrupt")

    return {"id": doc_id, "delay": round(delay, 3)}


async def fetch_all(doc_ids: list[int]) -> list[dict]:
    """
    Runs fetch_one concurrently for every id, and keeps every other
    result even if one call raises.
    """
    tasks = [fetch_one(doc_id) for doc_id in doc_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ok, failed = [], []
    for doc_id, result in zip(doc_ids, results):
        if isinstance(result, Exception):
            failed.append((doc_id, result))
        else:
            ok.append(result)

    return ok, failed


async def main() -> None:
    doc_ids = list(range(10))

    start = asyncio.get_event_loop().time()
    ok, failed = await fetch_all(doc_ids)
    elapsed = asyncio.get_event_loop().time() - start

    print(f"finished {len(ok)} ok, {len(failed)} failed in {elapsed:.3f}s")
    for item in sorted(ok, key=lambda r: r["id"]):
        print(f"  ok:   id={item['id']} delay={item['delay']}")
    for doc_id, err in failed:
        print(f"  FAIL: id={doc_id} -> {err}")


if __name__ == "__main__":
    asyncio.run(main())
