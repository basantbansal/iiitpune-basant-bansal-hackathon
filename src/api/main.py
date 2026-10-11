from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from src.api.routes import router

load_dotenv()

app = FastAPI(title="Institutional Risk Terminal API")

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

app.include_router(router)

import asyncio
from src.api.dependencies import get_state

@app.on_event("startup")
async def startup_event():
    state = get_state()
    # Explicit initialization path for prices, non-blocking with timeout
    asyncio.create_task(
        asyncio.to_thread(state.rebalancer.price_provider.refresh_prices, state.rebalancer.tickers, 5)
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
