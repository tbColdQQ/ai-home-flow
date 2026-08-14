from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, duty, images, leases, orders, qa, tasks
from app.db.migrations import migrate


app = FastAPI(title="home-flow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    migrate()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(leases.router, prefix="/api/leases", tags=["leases"])
app.include_router(duty.router, prefix="/api/duty", tags=["duty"])
app.include_router(images.router, prefix="/api/images", tags=["images"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(qa.router, prefix="/api/qa", tags=["qa"])
