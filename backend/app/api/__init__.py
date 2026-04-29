from fastapi import FastAPI

from app.api.routers import health, project


def register_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(project.router)
