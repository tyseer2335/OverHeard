"""FastAPI backend -- kicks off the research agent and serves the messy raw data.

Run:
    pip install -r requirements.txt
    uvicorn main:app --reload

Endpoints:
    GET  /health                       -> quick liveness check
    POST /gather   {product, ...}       -> start a gather job, returns job_id
    GET  /jobs/{job_id}                -> job status + counts + a small sample
    GET  /jobs/{job_id}/raw            -> download the full raw_data.jsonl for that job

Gathering can take a while (the agent makes many searches), so /gather runs in the
background and returns immediately with a job_id you poll.
"""

import os
import json
import uuid
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()  # pull keys from .env into the environment

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import run_research_agent

app = FastAPI(title="ReviewAgent -- messy data gatherer")

# where raw pulls get written
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# simple in-memory job store (fine for a hackathon; resets on restart)
JOBS = {}


class GatherRequest(BaseModel):
    product: str
    use_browser: bool = False        # also try X + Instagram (slow, may wall)
    max_iters: int = 16              # cap on agent search rounds
    model: str = "gpt-4o"


def _now():
    return datetime.now(tz=timezone.utc).isoformat()


def _run_job(job_id, req: GatherRequest):
    JOBS[job_id]["status"] = "running"
    try:
        items = run_research_agent(
            req.product, use_browser=req.use_browser,
            max_iters=req.max_iters, model=req.model,
        )
        path = os.path.join(DATA_DIR, f"{job_id}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it.to_dict()) + "\n")

        # per-source counts for a quick glance at what we got
        by_source = {}
        for it in items:
            by_source[it.source] = by_source.get(it.source, 0) + 1

        JOBS[job_id].update({
            "status": "done",
            "finished_at": _now(),
            "total_items": len(items),
            "by_source": by_source,
            "path": path,
            "sample": [it.to_dict() for it in items[:5]],
        })
    except Exception as e:
        JOBS[job_id].update({"status": "error", "error": str(e), "finished_at": _now()})


@app.get("/health")
def health():
    return {"ok": True, "time": _now()}


@app.post("/gather")
def gather(req: GatherRequest):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(400, "OPENAI_API_KEY not set on the server")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "job_id": job_id, "product": req.product, "status": "queued",
        "started_at": _now(), "use_browser": req.use_browser,
    }
    # run in a background thread so the request returns immediately
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "status": "queued",
            "poll": f"/jobs/{job_id}", "download": f"/jobs/{job_id}/raw"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


@app.get("/jobs/{job_id}/raw")
def job_raw(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    path = job.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(409, f"raw data not ready (status: {job.get('status')})")
    return FileResponse(path, media_type="application/x-ndjson",
                        filename=f"raw_{job_id}.jsonl")
