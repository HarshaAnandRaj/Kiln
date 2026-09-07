# SPDX-License-Identifier: Apache-2.0
# Copyright (C) Kiln Contributors — see LICENSE-SERVER
"""Shared Compute: jobs, capabilities, smart allocation. Pure python (testable)."""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field

JOB_TYPES = ("frame", "tile", "bake")
MAX_TASKS = 32
LEASE_S = {"frame": 60.0, "tile": 120.0, "bake": 120.0}


@dataclass
class WorkerCaps:
    user: str
    cpu: int = 4
    mem_gb: float = 8.0
    gpu: str | None = None
    blender: str = "4.2"
    share: bool = True
    load: float = 0.0
    rtt_ms: int = 50
    seen_at: float = field(default_factory=time.time)


@dataclass
class Task:
    task_id: str
    job_id: str
    idx: int
    spec: dict
    state: str = "waiting"  # waiting|leased|done|failed
    worker: str | None = None
    lease_exp: float = 0.0
    pct: int = 0
    result: dict | None = None


@dataclass
class Job:
    job_id: str
    room: str
    type: str
    params: dict
    by: str
    created: float = field(default_factory=time.time)
    tasks: list[Task] = field(default_factory=list)
    status: str = "open"  # open|done|cancelled


def new_job_id() -> str:
    return "j_" + uuid.uuid4().hex[:10]


def expand_job(room: str, by: str, type: str, params: dict) -> Job:
    assert type in JOB_TYPES, f"unknown job type {type}"
    job = Job(job_id=params.pop("job_id", None) or new_job_id(), room=room, type=type, params=dict(params), by=by)
    if type == "frame":
        fs, fe = int(params.get("frame_start", 1)), int(params.get("frame_end", 1))
        if fe < fs:
            fs, fe = fe, fs
        n = min(fe - fs + 1, MAX_TASKS)
        for i in range(n):
            f = fs + i
            job.tasks.append(Task(task_id=f"{job.job_id}:f{f}", job_id=job.job_id, idx=i,
                                  spec={"frame": f, "samples": params.get("samples", 32),
                                        "engine": params.get("engine", "CYCLES")}))
    elif type == "tile":
        g = max(1, min(int(params.get("grid", 2)), 5))
        n = min(g * g, MAX_TASKS)
        for ty in range(g):
            for tx in range(g):
                if len(job.tasks) >= n:
                    break
                job.tasks.append(Task(task_id=f"{job.job_id}:t{tx}_{ty}", job_id=job.job_id,
                                      idx=len(job.tasks),
                                      spec={"tx": tx, "ty": ty, "grid": g,
                                            "frame": params.get("frame", 1),
                                            "x0": tx / g, "y0": ty / g,
                                            "x1": (tx + 1) / g, "y1": (ty + 1) / g,
                                            "border": params.get("border", 0.05)}))
    else:  # bake: single task to beefiest worker
        job.tasks.append(Task(task_id=f"{job.job_id}:bake", job_id=job.job_id, idx=0,
                              spec={"kind": params.get("kind", "physics"),
                                    "target": params.get("target_kiln_id")}))
    return job


def score_worker(w: WorkerCaps, job: Job, now: float | None = None) -> float:
    """Higher = better. -inf veto if not eligible."""
    now = now or time.time()
    if not w.share:
        return float("-inf")
    if now - w.seen_at > 30.0:
        return float("-inf")
    s = 10.0 * w.cpu + 5.0 * (w.mem_gb / 8.0) - 30.0 * w.load - w.rtt_ms / 50.0
    if w.gpu and job.params.get("want_gpu", True):
        s += 20.0
    want_bl = str(job.params.get("blend_version", ""))
    if want_bl and not str(w.blender).startswith(want_bl.rsplit(".", 1)[0]):
        s -= 1000.0  # version mismatch veto-ish
    return s


def pick_task_for_worker(job: Job, worker: str, now: float | None = None) -> Task | None:
    """Best waiting (or expired-lease) task for this worker. Bake = worker-agnostic single."""
    now = now or time.time()
    for t in job.tasks:
        if t.state == "done":
            continue
        if t.state == "leased" and t.lease_exp > now and t.worker != worker:
            continue
        # expired or waiting → claimable
        return t
    return None


def best_worker(workers: list[WorkerCaps], job: Job) -> WorkerCaps | None:
    scored = sorted(((score_worker(w, job), w) for w in workers), reverse=True, key=lambda x: x[0])
    if not scored or scored[0][0] == float("-inf"):
        return None
    return scored[0][1]


def job_progress(job: Job) -> dict:
    done = sum(1 for t in job.tasks if t.state == "done")
    pcts = [t.pct for t in job.tasks]
    avg = int(sum(pcts) / len(pcts)) if pcts else 0
    return {"job_id": job.job_id, "type": job.type, "done": done,
            "total": len(job.tasks), "avg_pct": avg,
            "status": "done" if done == len(job.tasks) else job.status}
