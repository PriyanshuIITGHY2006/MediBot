"""Bill split endpoints (Phase 15.1): POST /api/v1/bill/parse (a pasted list -> lines), POST /api/v1/bill/plan
(lines -> the cheapest way to buy them across pharmacies, plus the as-asked, one-pharmacy and Jan Aushadhi plans),
POST /api/v1/bill/read (a photo of a bill / prescription -> proposed lines; the image is the raw request body,
never stored; ?vision=1 opts in to the AI reader, which sends the photo to an outside service)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from medibot.api.deps import bot
from medibot.api.schemas import BillParseIn, BillPlanIn

router = APIRouter()


@router.post("/api/v1/bill/parse")
def bill_parse(body: BillParseIn):
    from medibot.billsplit import parse_list
    return {"lines": parse_list(body.text)}


@router.post("/api/v1/bill/plan")
def bill_plan(body: BillPlanIn):
    from medibot.billsplit import split_bill
    return split_bill(bot(), [i.model_dump() for i in body.items], body.allow_alternatives, body.max_pharmacies)


@router.post("/api/v1/bill/read")
async def bill_read(request: Request, vision: bool = False):
    from starlette.concurrency import run_in_threadpool

    from medibot.billread import MAX_BYTES, ReadError, read_bill
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        return JSONResponse({"error": "photo must be under 8 MB"}, status_code=413)
    data = await request.body()
    try:
        return await run_in_threadpool(read_bill, bot(), data, vision)
    except ReadError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
