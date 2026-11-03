"""HTTP service: POST /chat and GET /health on port 8000.

Ingestion runs in a background thread at start-up, so the process answers /health
(503) immediately and flips to 200 only when the documents are indexed.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import date
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Body, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, load_settings
from app.data import repository
from app.data.db import connect, ensure_schema
from app.ingestion.pipeline import run_ingestion
from app.llm.client import LLM
from app.llm.factory import make_llm
from app.orchestrator.engine import Orchestrator
from app.orchestrator.session import SessionStore
import time

from app.logctx import deadline_var, request_id_var
from app.privacy import PersonalDataFilter
from app.retrieval.retriever import Retriever

logger = logging.getLogger("veltrix.api")

REQUEST_BUDGET_SECONDS = 26.0   # the brief allows 30 s per request; leave room to answer


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    loggers = [logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")]
    for handler in [h for logger_ in loggers for h in logger_.handlers]:
        if not any(isinstance(f, PersonalDataFilter) for f in handler.filters):
            handler.addFilter(PersonalDataFilter())


class AppState:
    def __init__(self) -> None:
        self.ready = False
        self.error: Optional[str] = None
        self.orchestrator: Optional[Orchestrator] = None
        self.sessions = SessionStore()


def ingest(settings: Settings, state: AppState, llm: LLM) -> None:
    try:
        conn = connect(settings.db_path)
        ensure_schema(conn)
        result = run_ingestion(settings.manifest_path, settings.corpus_dir, conn)
        conn.close()
        for doc_id, reason in result.failures.items():
            logger.error("ingestion_failed doc_id=%s reason=%s", doc_id, reason)
        for warning in result.warnings:
            logger.warning("ingestion_warning %s", warning)
        state.orchestrator = Orchestrator(Retriever(result.chunks), llm)
        state.ready = True
        logger.info("ingestion_done documents=%d chunks=%d holiday_rows=%d ocr_docs=%d failures=%d model=%s",
                    len(result.documents), len(result.chunks), result.holiday_rows, len(result.ocr_pages),
                    len(result.failures), getattr(llm, "_model", "n/a"))
    except Exception as exc:   # the service stays up and /health stays 503
        state.error = type(exc).__name__
        logger.exception("ingestion_crashed")


def create_app(settings: Optional[Settings] = None, llm: Optional[LLM] = None, background: bool = True) -> FastAPI:
    configure_logging()
    settings = settings or load_settings()
    llm = llm or make_llm(settings)
    state = AppState()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if background:
            threading.Thread(target=ingest, args=(settings, state, llm), daemon=True).start()
        elif not state.ready:
            ingest(settings, state, llm)
        yield

    app = FastAPI(title="Veltrix PeopleOps Assistant", lifespan=lifespan)
    app.state.veltrix = state

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid request body"}, status_code=400)

    @app.get("/health")
    def health() -> JSONResponse:
        if state.ready:
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "starting"}, status_code=503)

    @app.post("/chat")
    def chat(payload: Any = Body(default=None), x_employee_id: Optional[str] = Header(default=None)) -> JSONResponse:
        if not state.ready:
            return JSONResponse({"error": "service is starting"}, status_code=503)
        conn = connect(settings.db_path)
        try:
            requester = repository.get_employee(conn, x_employee_id.strip()) if x_employee_id and x_employee_id.strip() else None
            if requester is None:
                return JSONResponse({"error": "unknown or missing X-Employee-Id"}, status_code=401)
            if not isinstance(payload, dict):
                return JSONResponse({"error": "invalid request body"}, status_code=400)
            session_id, message = payload.get("session_id"), payload.get("message")
            if not isinstance(session_id, str) or not session_id.strip() or not isinstance(message, str) or not message.strip():
                return JSONResponse({"error": "session_id and message are required strings"}, status_code=400)
            session = state.sessions.claim(session_id, requester.employee_id)
            if session is None:
                return JSONResponse({"error": "this session belongs to another employee"}, status_code=403)

            request_id = str(uuid.uuid4())
            token = request_id_var.set(request_id)
            deadline_token = deadline_var.set(time.monotonic() + REQUEST_BUDGET_SECONDS)
            try:
                response = state.orchestrator.handle(conn, requester, session, message, settings.app_today)
            finally:
                request_id_var.reset(token)
                deadline_var.reset(deadline_token)
            logger.info("chat request_id=%s employee=%s route=%s citations=%d tool_calls=%d pending=%s",
                        request_id, requester.employee_id, response.route, len(response.citations),
                        len(response.tool_calls), response.pending_confirmation)
            return JSONResponse(response.to_dict(request_id))
        finally:
            conn.close()

    return app


app = create_app()
