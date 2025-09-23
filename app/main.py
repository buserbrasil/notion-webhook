import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import webhooks
from .services import notion

# Silence upcoming python-multipart import warning
os.environ.setdefault("PYTHON_MULTIPART_SILENCE_DEPRECATION", "1")

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting %s", settings.APP_NAME)
    if not settings.NOTION_API_KEY:
        logger.warning("NOTION_API_KEY not set. Some functionality may be limited.")

    if settings.has_database_credentials:
        try:
            await notion.ensure_content_storage()
        except Exception:
            # Exception already logged within ensure_content_storage
            raise

    logger.info("Application startup complete")
    try:
        yield
    finally:
        await notion.aclose_http_client()
        logger.info("Shutting down %s", settings.APP_NAME)

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="API for receiving Notion webhooks",
    version="0.1.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhooks.router)

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "online", "message": "Notion Webhook service is running"}

@app.get("/health")
async def health():
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}
