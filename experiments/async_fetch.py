"""
async_fetch.py

Maps to: Agent 1's parallel parse orchestration — specifically the part
where the worker pulls a PR's changed-file contents from GitHub before
anything can be parsed.

Step 1: synchronous baseline. Fetch N files one at a time, no asyncio.
This exists to get a real "before" number — later versions compare
against it instead of just assuming async is faster.

Step 2: asyncio.gather, no concurrency cap. Point is to see the
event-loop mechanics work — not yet production-shaped. Deliberately the
"what if we don't bound it" before-picture, same role the sync version
played for step 1.

Step 3 (this version): bounded semaphore. Same coroutines, same gather —
the only change is an asyncio.Semaphore(limit) wrapping each fetch, so at
most `limit` are in flight at once instead of all 20 simultaneously. This
is the shape that's actually safe to point at a real rate-limited API.
"""

import asyncio
import random
import time


def fetch_file(file_id: int) -> str:
    """Stand-in for a GitHub content fetch: wait, then get bytes back.
    Fake latency instead of a real HTTP call, same shape."""
    latency = random.uniform(0.1, 0.5)
    time.sleep(latency)
    return f"contents of file {file_id}"


def fetch_all_sync(file_ids: list[int]) -> list[str]:
    return [fetch_file(fid) for fid in file_ids]


async def fetch_file_async(file_id: int) -> str:
    """Same fake latency, but await asyncio.sleep instead of time.sleep —
    that's the whole difference that lets the event loop run other
    coroutines during the wait instead of blocking the thread."""
    latency = random.uniform(0.1, 0.5)
    await asyncio.sleep(latency)
    return f"contents of file {file_id}"


async def fetch_all_concurrent(file_ids: list[int]) -> list[str]:
    return await asyncio.gather(*(fetch_file_async(fid) for fid in file_ids))


async def fetch_file_bounded(file_id: int, sem: asyncio.Semaphore) -> str:
    async with sem:
        return await fetch_file_async(file_id)


async def fetch_all_bounded(file_ids: list[int], limit: int) -> list[str]:
    sem = asyncio.Semaphore(limit)
    return await asyncio.gather(*(fetch_file_bounded(fid, sem) for fid in file_ids))


if __name__ == "__main__":
    file_ids = list(range(20))

    start = time.perf_counter()
    results = fetch_all_sync(file_ids)
    elapsed = time.perf_counter() - start
    print(f"Fetched {len(results)} files sequentially in {elapsed:.2f}s")

    start = time.perf_counter()
    results = asyncio.run(fetch_all_concurrent(file_ids))
    elapsed = time.perf_counter() - start
    print(f"Fetched {len(results)} files concurrently (no cap) in {elapsed:.2f}s")

    # Sweeping `limit` here is for the experiment only, to see the curve.
    # In the real worker, the limit would be one fixed constant (e.g. ~8,
    # chosen from GitHub's documented concurrent-request / secondary
    # rate-limit tolerance and tuned against real 403 / Retry-After
    # responses) — never derived from a given PR's file count. File count
    # only changes how many batches that fixed limit needs, not the limit
    # itself.
    for limit in (2, 5, 10):
        start = time.perf_counter()
        results = asyncio.run(fetch_all_bounded(file_ids, limit))
        elapsed = time.perf_counter() - start
        print(f"Fetched {len(results)} files concurrently (limit={limit}) in {elapsed:.2f}s")
