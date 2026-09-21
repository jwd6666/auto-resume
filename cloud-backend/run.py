"""开发/部署启动入口：python run.py"""
from __future__ import annotations

import uvicorn

from app.core.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
