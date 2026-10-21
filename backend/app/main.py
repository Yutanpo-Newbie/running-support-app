from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(
    title="Running Support App Backend",
    description="ランニングルート提案および音声ナビゲーションAPI",
    version="0.1.0",
)

app.include_router(router)


###[解説]:ルートURLに対するHTTP GETリクエストを受け取るため###
@app.get("/")
###[解説]:ルートURLにアクセスがあった場合のレスポンス
def root():
    return {
        "message": "Running Support App Backend is running"
    }