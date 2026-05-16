"""FastAPI application with job queue, credential manager, and WebSocket."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router, set_job_manager, set_cred_manager
from api.jobs import JobManager
from api.credentials import CredentialManager

logger = logging.getLogger(__name__)

# Global singletons
_job_manager = JobManager()
_cred_manager = CredentialManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("Starting job worker...")
    _job_manager.start_worker()
    set_job_manager(_job_manager)
    logger.info("Job worker started. %d jobs in history", len(_job_manager.get_recent(1)))

    # Credential manager
    set_cred_manager(_cred_manager)
    if _cred_manager.has_credentials():
        status = _cred_manager.get_status()
        logger.info(
            "Credentials configured: %s (%s, %s, %s)",
            status.get("account_id", "unknown"),
            status.get("prop_firm", "?"),
            status.get("account_type", "?"),
            status.get("phase", "?"),
        )
    else:
        logger.info("No credentials configured. Use POST /api/credentials to set up.")

    yield  # Server runs here

    # Shutdown
    logger.info("Shutting down job worker...")
    _job_manager.stop()
    logger.info("Job worker stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PropFirm Bot API",
        description="Multi-prop-firm trading bot with secure credential management",
        version="2.0.0",
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
