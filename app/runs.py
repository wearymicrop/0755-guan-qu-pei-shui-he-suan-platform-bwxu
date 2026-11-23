from time import perf_counter
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.errors import InputError
from app.manifest import identity, make_manifest
from app.pipeline import calculate, validate
from app.samples import load_sample
from app.settings import PROJECT

router = APIRouter(prefix="/api/runs", tags=["归档与证据"])


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample: str | None = None
    data: dict[str, Any] | None = None
    idempotency_key: str | None = None


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outlet: str
    amount_l: int


def archive_run(store, data, sample, idempotency_key=None):
    validate(data)
    digest = identity(data, sample)
    if idempotency_key is not None:
        bound = store.resolve_idempotency(idempotency_key)
        if bound is not None and bound != digest:
            raise InputError("IDEMPOTENCY_CONFLICT", "幂等键已绑定另一来源输入，禁止改派")
    existing = store.find(digest)
    if existing is not None:
        if idempotency_key is not None:
            store.bind_idempotency(idempotency_key, digest)
        return {**existing, "reused": True}
    begin = perf_counter()
    result = calculate(data)
    elapsed_ms = round((perf_counter() - begin) * 1000, 3)
    record = {"id": digest, "manifest": make_manifest(data, sample, digest, elapsed_ms), "input": data, "result": result}
    stored, reused = store.save(record)
    if idempotency_key is not None:
        store.bind_idempotency(idempotency_key, digest)
    return {**stored, "reused": reused}


@router.post("")
def create_run(body: Submission, request: Request):
    if (body.sample is None) == (body.data is None):
        raise InputError("CHOOSE_SOURCE", "请选择一个样例或提交数据")
    data = load_sample(body.sample) if body.sample is not None else body.data
    return archive_run(request.app.state.archive, data, body.sample, body.idempotency_key)


@router.get("/{run_id}")
def get_run(run_id: str, request: Request):
    return request.app.state.archive.get(run_id)


@router.post("/{run_id}/rerun")
def rerun(run_id: str, request: Request):
    store = request.app.state.archive
    stored = store.get(run_id)
    return archive_run(store, stored["input"], stored["manifest"]["sample"])


@router.get("/{run_id}/export")
def export_run(run_id: str, request: Request):
    return JSONResponse(request.app.state.archive.get(run_id), headers={
        "Content-Disposition": f'attachment; filename="{PROJECT}-{run_id[:12]}.json"'
    })


@router.post("/{run_id}/confirmations")
def confirm_outlet(run_id: str, body: Confirmation, request: Request):
    store = request.app.state.archive
    record = store.get(run_id)
    actual = {row["outlet"]: row["allocated_l"]
              for row in record["result"]["tail"]["allocations"] if row["allocated_l"]}
    if body.outlet not in actual:
        raise InputError("CONFIRM_MISMATCH", "该斗口本轮没有实配记录", 404)
    if body.amount_l != actual[body.outlet]:
        raise InputError("CONFIRM_MISMATCH", "确认量必须等于归档实配量，禁止改派")
    payload = {"run_id": run_id, "outlet": body.outlet, "amount_l": body.amount_l}
    saved, created = store.confirm(run_id, body.outlet, body.amount_l, payload)
    return {**saved, "created": created}


@router.get("/{run_id}/confirmations")
def list_confirmations(run_id: str, request: Request):
    store = request.app.state.archive
    store.get(run_id)
    rows = store.confirmations(run_id)
    return {"run_id": run_id, "confirmed": rows,
            "confirmed_l": sum(row["amount_l"] for row in rows), "count": len(rows)}
