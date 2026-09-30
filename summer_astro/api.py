from __future__ import annotations
import asyncio
import hmac
import os
import time
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool
from .contracts import ForecastRequest, Strict, aware, digest
from .engine import SummerEngine, load_policy
from .astronomy import verify_ephemeris
from .storage import ForecastStore
from . import __version__
from .historical import HistoricalTest, record_test, report_tests

class Outcome(Strict):
    event_id: str
    run_id: str
    occurred_at: datetime
    known_at: datetime
    primary_domain: str
    action: str = "unknown"
    development_only: bool = False

def create_app(data_path=None,token=None):
    data_path=data_path or os.environ.get("SUMMER_DB","./data/forecasts.sqlite")
    token=token if token is not None else os.environ.get("SUMMER_API_TOKEN","")
    store=ForecastStore(data_path)
    engine=SummerEngine(store)
    security=HTTPBearer(auto_error=False)
    app=FastAPI(title="Summer Astro Engine",version=__version__,docs_url=None,redoc_url=None)
    app.state.store=store;app.state.engine=engine
    semaphore=asyncio.Semaphore(1)
    telemetry={"requests":0,"completed":0,"errors":0,"timeouts":0,"last_duration_seconds":None}

    def auth(credentials: HTTPAuthorizationCredentials | None=Depends(security)):
        if not token: raise HTTPException(503,"service key not configured")
        if credentials is None or not hmac.compare_digest(credentials.credentials,token):
            raise HTTPException(401,"invalid credentials")

    @app.middleware("http")
    async def body_limit(request,call_next):
        # Read and bound actual bytes; do not trust Content-Length alone.
        if request.method in {"POST","PUT"}:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>1_000_000:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail":"request too large"},status_code=413)
            request._body=bytes(body)
        return await call_next(request)

    @app.get("/health")
    def health():
        try: checksum=verify_ephemeris()
        except Exception: raise HTTPException(503,"ephemeris unavailable")
        return {"status":"ok","version":__version__,"release_status":"experimental-unvalidated",
            "ephemeris_manifest_hash":checksum,"authentication_configured":bool(token)}

    @app.get("/",response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent/"ui.html").read_text()

    @app.get("/source")
    def source():
        root=Path(__file__).parent.parent
        module=Path(__file__).parent
        paths=[p for p in module.rglob("*") if p.is_file() and p.suffix in {".py",".json",".html",".se1"}]
        paths += [root/name for name in ["requirements-lock.txt","requirements.txt","Dockerfile","compose.yaml",
            "README_AR.md","NOTICE","LICENSE","LICENSE-SWISSEPH"] if (root/name).is_file()]
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(paths): archive.write(path,path.relative_to(root).as_posix())
        return Response(buffer.getvalue(),media_type="application/zip",headers={
            "Content-Disposition":'attachment; filename="Summer-Astro-Engine-2.0.0-source.zip"'})

    @app.get("/schema",dependencies=[Depends(auth)])
    def schema(): return ForecastRequest.model_json_schema()

    @app.get("/metrics",dependencies=[Depends(auth)])
    def metrics(): return {**telemetry,"records":store.counts()}

    @app.get("/policy",dependencies=[Depends(auth)])
    def policy(): return load_policy()

    @app.post("/historical-tests",dependencies=[Depends(auth)])
    def historical_test(value: HistoricalTest):
        try: return record_test(store,value)
        except ValueError as e: raise HTTPException(422,str(e))

    @app.get("/historical-tests",dependencies=[Depends(auth)])
    def historical_report(engine_version: str | None=None):
        return report_tests(store,engine_version)

    @app.get("/historical-tests/export",dependencies=[Depends(auth)])
    def historical_export():
        return {"records":store.list_kind("historical_test"),"format":"immutable-labeled-tests-1"}

    @app.post("/forecast",dependencies=[Depends(auth)])
    async def forecast(request: ForecastRequest):
        started=time.monotonic();telemetry["requests"]+=1
        if semaphore.locked(): raise HTTPException(429,"engine busy; retry the same request")
        async with semaphore:
            try:
                result=await run_in_threadpool(engine.forecast,request)
                telemetry["completed"]+=1
                return result
            except ValueError as e:
                telemetry["errors"]+=1;raise HTTPException(422,str(e))
            except Exception:
                telemetry["errors"]+=1;raise HTTPException(503,"forecast failed; no partial forecast published")
            finally: telemetry["last_duration_seconds"]=round(time.monotonic()-started,3)

    @app.get("/runs/{run_id}",dependencies=[Depends(auth)])
    def run(run_id: str):
        record=store.get(run_id)
        if record is None: raise HTTPException(404,"run not found")
        return record

    @app.post("/outcomes",dependencies=[Depends(auth)])
    def outcome(value: Outcome):
        from .contracts import DOMAINS
        if value.primary_domain not in DOMAINS: raise HTTPException(422,"unknown domain")
        if store.get(value.run_id) is None: raise HTTPException(404,"forecast run not found")
        try:
            occurred=aware(value.occurred_at);known=aware(value.known_at)
            if known<occurred: raise ValueError("outcome cannot be known before it occurs")
            if known>datetime.now(timezone.utc): raise ValueError("future outcomes cannot be recorded as observed")
            payload=value.model_dump(mode="json")
            record_id="outcome-"+digest(payload)[:32]
            store.append(record_id,"outcome",known.isoformat(),payload)
            return {"record_id":record_id,"status":"recorded"}
        except ValueError as e: raise HTTPException(422,str(e))

    return app

app=create_app()
