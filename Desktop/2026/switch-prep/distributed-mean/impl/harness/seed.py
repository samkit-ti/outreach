#!/usr/bin/env python3
"""Fixture-seeding harness — a TEST TOOL, not a system feature.

The system aggregates pre-existing inputs (the federated-learning setting);
this script plays the role of the nodes: it PUTs F fixture files into MinIO
under fixtures/{runId}/ and prints the inputUris. With --submit it POSTs the
job and polls to completion.

Examples:
  python3 seed.py --f 1000 --c 100000 --submit           # the demo job
  python3 seed.py --values "1,2,3;4,5,6" --submit        # the brief's example
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from urllib.request import Request, urlopen

import boto3
import numpy as np


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--f", type=int, help="number of files (random fixtures)")
    parser.add_argument("--c", type=int, help="values per file")
    parser.add_argument("--values", help='explicit fixtures: "1,2,3;4,5,6"')
    parser.add_argument("--format", choices=["csv", "f64"], default="csv")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    bucket = env("S3_BUCKET", "distributed-mean")
    api = env("API_URL", "http://localhost:8080")
    s3 = boto3.client(
        "s3",
        endpoint_url=env("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=env("S3_ACCESS_KEY", "dmadmin"),
        aws_secret_access_key=env("S3_SECRET_KEY", "dmsecret"),
        region_name="us-east-1",
    )

    if args.values:
        rows = [
            np.array([float(x) for x in chunk.split(",")], dtype=np.float64)
            for chunk in args.values.split(";")
        ]
        c = rows[0].shape[0]
        if any(r.shape[0] != c for r in rows):
            print("all value rows must have the same length", file=sys.stderr)
            return 2
    else:
        if not args.f or not args.c:
            parser.error("either --values or both --f and --c")
        rng = np.random.default_rng(args.seed)
        c = args.c
        rows = None  # generated lazily below to keep memory flat

    run_id = uuid.uuid4().hex[:12]
    f_count = len(rows) if rows is not None else args.f
    uris: list[str] = []
    t0 = time.time()
    for i in range(f_count):
        vec = rows[i] if rows is not None else np.random.default_rng(args.seed + i).random(c)
        if args.format == "csv":
            key = f"fixtures/{run_id}/{i}.csv"
            body = ("\n".join(repr(float(x)) for x in vec) + "\n").encode()
        else:
            key = f"fixtures/{run_id}/{i}.f64"
            body = np.ascontiguousarray(vec, dtype="<f8").tobytes()
        s3.put_object(Bucket=bucket, Key=key, Body=body)
        uris.append(f"s3://{bucket}/{key}")
        if (i + 1) % 200 == 0:
            print(f"seeded {i + 1}/{f_count} files…", file=sys.stderr)
    print(f"seeded {f_count} files in {time.time() - t0:.1f}s", file=sys.stderr)

    if not args.submit:
        json.dump({"inputUris": uris, "c": c}, sys.stdout)
        print()
        return 0

    request = Request(
        f"{api}/jobs",
        data=json.dumps({"inputUris": uris, "c": c}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        job = json.load(response)
    job_id = job["jobId"]
    print(f"job {job_id} submitted (F={f_count}, C={c})", file=sys.stderr)

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        with urlopen(f"{api}/jobs/{job_id}") as response:
            status = json.load(response)
        print(
            f"  {status['status']:>10}  progress={status.get('progress', 0):.2%}",
            file=sys.stderr,
        )
        if status["status"] in ("completed", "failed"):
            print(json.dumps({"jobId": job_id, "status": status["status"]}))
            if status["status"] == "completed":
                print(f"result: {api}/jobs/{job_id}/result?inline=1", file=sys.stderr)
                return 0
            return 1
        time.sleep(2)
    print("timeout waiting for job", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
