"""FastAPI application setup."""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from augustus.api.dependencies import init_services
from augustus.api.routes import (
    agents,
    sessions,
    trajectories,
    proposals,
    flags,
    search,
    usage,
    settings,
    evaluator_prompts,
    annotations,
    orchestrator,
    activity,
    events,
)

from augustus.models.dataclasses import EvaluatorPrompt
from augustus.services.evaluator import (
    DEFAULT_EVALUATOR_PROMPT,
    DEFAULT_EVALUATOR_PROMPT_RATIONALE,
    DEFAULT_EVALUATOR_PROMPT_VERSION,
)
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)


def _arm_shutdown_watchdog(deadline: float = 6.0) -> None:
    """Force-exit if the process doesn't terminate within *deadline* seconds.

    On Windows, ``asyncio.run()`` blocks in ``shutdown_default_executor()``
    when ChromaDB / SQLite leave non-daemon threads alive.  This watchdog
    runs regardless of whether the app was launched via ``main.py`` or
    ``uvicorn --reload``.
    """
    def _watchdog():
        threading.Event().wait(deadline)
        logger.warning(
            "Shutdown watchdog: process still alive after %.0fs — forcing exit",
            deadline,
        )
        os._exit(0)

    t = threading.Thread(target=_watchdog, daemon=True, name="shutdown-watchdog")
    t.start()


async def _seed_default_evaluator_prompt(memory: MemoryService) -> None:
    """Insert the default v0.1 evaluator prompt if no prompts exist yet."""
    existing = await memory.list_evaluator_prompts()
    if existing:
        return

    prompt = EvaluatorPrompt(
        version_id=DEFAULT_EVALUATOR_PROMPT_VERSION,
        prompt_text=DEFAULT_EVALUATOR_PROMPT,
        change_rationale=DEFAULT_EVALUATOR_PROMPT_RATIONALE,
        is_active=True,
    )
    await memory.store_evaluator_prompt(prompt)
    logger.info("Seeded default evaluator prompt %s", DEFAULT_EVALUATOR_PROMPT_VERSION)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize services on startup, orchestrator if needed."""
    import asyncio

    from augustus.api.dependencies import get_container

    container = get_container()
    # Only init if not already done (main.py pre-initializes when running via CLI)
    if container.memory is None:
        container = init_services()
    logger.info("Augustus API services initialized")

    # Seed the default evaluator prompt if none exists
    await _seed_default_evaluator_prompt(container.memory)

    # If no orchestrator exists yet (dev mode — running via uvicorn directly),
    # create and start one so the Resume button actually works.
    orch_task = None
    if container.orchestrator is None:
        from augustus.api.dependencies import create_orchestrator

        create_orchestrator()
        orch_task = asyncio.create_task(container.orchestrator.start())
        logger.info("Orchestrator created and started via lifespan")

    yield

    # Arm the watchdog FIRST — if anything below hangs, we still exit.
    _arm_shutdown_watchdog(deadline=6.0)

    # Shutdown: stop orchestrator if we started it
    if orch_task is not None and container.orchestrator is not None:
        try:
            await container.orchestrator.stop(timeout=3.0)
        except Exception:
            pass
        if not orch_task.done():
            orch_task.cancel()
            try:
                await asyncio.wait_for(orch_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    logger.info("Augustus API shutting down")


app = FastAPI(title="Augustus API", version="0.9.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler — catches any unhandled error and returns the
# traceback in the response body so the frontend (and developer) can see
# what actually went wrong instead of a bare "Internal Server Error".
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


# Include routers
app.include_router(agents.router)
app.include_router(sessions.router)
app.include_router(trajectories.router)
app.include_router(proposals.router)
app.include_router(flags.router)
app.include_router(search.router)
app.include_router(usage.router)
app.include_router(settings.router)
app.include_router(evaluator_prompts.router)
app.include_router(annotations.router)
app.include_router(orchestrator.router)
app.include_router(activity.router)
app.include_router(events.router)


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.9.0"}


# SPA serving (production — frontend/dist served by FastAPI)
from fastapi.responses import FileResponse

frontend_dist = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    # Mount assets directory
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes."""
        # Don't intercept API routes
        if full_path.startswith("api/"):
            return {"error": "Not found"}

        index = frontend_dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Frontend not built"}
