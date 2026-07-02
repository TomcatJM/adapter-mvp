from __future__ import annotations

from fastapi import FastAPI, HTTPException

from codegraph_worker.service import CodeGraphQuery, CodeGraphWorker, WorkerConfig, WorkerError


app = FastAPI(title="CodeGraph Worker", version="0.1.0")
worker = CodeGraphWorker(WorkerConfig.from_env())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/codegraph/query")
def query_codegraph(request: CodeGraphQuery) -> dict:
    try:
        return worker.query(request)
    except WorkerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

