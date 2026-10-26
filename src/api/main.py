import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from src.api.routes import router
from src.api.dependencies import get_state

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Intentional application startup lifecycle:
    state = get_state()
    # Perform clean session startup (clears transient scan results, preserves ledger)
    await state.initialize_clean_session()
    # Non-blocking background price warm-up
    asyncio.create_task(
        asyncio.to_thread(state.rebalancer.price_provider.refresh_prices, state.rebalancer.tickers, 5)
    )
    yield

app = FastAPI(title="Institutional Risk Terminal API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
