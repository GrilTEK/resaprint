from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.exceptions import NotAuthenticatedHtml
from app.routers import (
    admin_ui,
    audit_log,
    auth,
    config,
    health,
    parsers,
    print_jobs,
    reservations,
    stations,
)

app = FastAPI(title="ResaPrint", version="0.1.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(NotAuthenticatedHtml)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedHtml) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(reservations.router)
app.include_router(print_jobs.router)
app.include_router(stations.router)
app.include_router(parsers.router)
app.include_router(audit_log.router)
app.include_router(config.router)
app.include_router(admin_ui.router)
