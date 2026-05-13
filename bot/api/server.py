"""FastAPI application with job queue and WebSocket support."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router, set_job_manager
from api.jobs import JobManager

logger = logging.getLogger(__name__)

# Global job manager (singleton)
_job_manager = JobManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("Starting job worker...")
    _job_manager.start_worker()
    set_job_manager(_job_manager)
    logger.info(f"Job worker started. {len(_job_manager.get_recent(1))} jobs in history")

    yield  # Server runs here

    # Shutdown
    logger.info("Shutting down job worker...")
    _job_manager.stop()
    logger.info("Job worker stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PropFirm Bot API",
        version="1.0.0",
        lifespan=lifespan
    )

    # CORS for dashboard access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify your dashboard domain
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


# For direct execution: uvicorn api.server:create_app
app = create_app()
