import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

load_dotenv(Path(os.environ["APP_CONFIG_DIR"]) / ".env")

import uvicorn  # noqa: E402

import applications  # noqa: E402
from main import app  # noqa: E402

if __name__ == "__main__":
    applications.operator_key()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=18780,
        loop="asyncio",
        http="h11",
        ws="none",
        access_log=False,
    )
