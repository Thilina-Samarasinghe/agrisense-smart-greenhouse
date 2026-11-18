"""FastAPI entry point. Run with: uvicorn app.main:app --reload

The simulation service is created in the lifespan handler, so importing this module is cheap
and tests can build their own app with `create_app(Settings(...))`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agrisense_core import __version__
from app.api import control, data, health, sim
from app.config import Settings, settings
from app.db.session import Database
from app.services.simulation import SimulationService
from app.ws import live


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(cfg.database_url)
        db.create_all()
        service = SimulationService(cfg, db)
        app.state.settings = cfg
        app.state.service = service
        if cfg.autostart:
            await service.start()
        try:
            yield
        finally:
            await service.stop()
            db.dispose()

    app = FastAPI(title=cfg.app_name, version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (health, sim, control, data):
        app.include_router(module.router, prefix="/api")
    app.include_router(live.router)
    return app


app = create_app()
