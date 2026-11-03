"""Start one authenticated, loopback-only MLX model process on macOS."""

import fcntl
import json
import os
import platform
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path(
    os.getenv(
        "APP_CONFIG_DIR", Path.home() / "Library/Application Support/Phishing Rehearsal"
    )
)
DATA = PROFILE / "data" / "qwen-mlx"
LOG = DATA / "server.log"
PID = DATA / "server.pid"
URL = "http://127.0.0.1:18082"
values = dotenv_values(PROFILE / ".env")
KEY = (
    os.getenv("LOCAL_TTS_API_KEY")
    or values.get("LOCAL_TTS_API_KEY")
    or dotenv_values(ROOT / ".env").get("LAB_API_KEY")
)


def status():
    request = urllib.request.Request(URL + "/v1/info", headers={"X-API-Key": KEY or ""})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.load(response)
        if data.get("provider") != "qwen" or data.get("runtime") not in (None, "mlx"):
            raise RuntimeError("Port 18082 is used by a different model server")
        return data
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            "Port 18082 authentication failed; existing server was kept"
        ) from error
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def up():
    if status() is not None:
        print("Mac Qwen server is already running.")
        return
    with LOG.open("ab", buffering=0) as output:
        LOG.chmod(0o600)
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "serve"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
    PID.write_text(str(process.pid))
    PID.chmod(0o600)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"Mac model server exited; inspect {LOG}")
        if status() is not None:
            print(
                f"Mac Qwen server started. Loading status: bash ai.sh status. Log: {LOG}"
            )
            return
        time.sleep(0.1)
    print(f"Mac Qwen process is starting. Check bash ai.sh status. Log: {LOG}")


def stop():
    if not PID.is_file():
        print("No managed Mac model process.")
        return
    pid = int(PID.read_text())
    command = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False
    ).stdout
    if str(Path(__file__).resolve()) + " serve" not in command:
        PID.unlink(missing_ok=True)
        print("Managed Mac model process is no longer running.")
        return
    os.kill(pid, signal.SIGTERM)
    PID.unlink(missing_ok=True)
    print("Mac Qwen server stopped; models and voices were retained.")


def serve():
    if not KEY:
        raise RuntimeError("Configure LOCAL_TTS_API_KEY or LAB_API_KEY")
    os.environ.update(
        PROVIDER="qwen",
        INFERENCE_DEVICE="mlx",
        LAB_API_KEY=KEY,
        DATA_DIR=str(DATA),
        HF_HUB_CACHE=str(PROFILE / "models" / "huggingface"),
        MODEL_ID=os.getenv(
            "QWEN_MLX_MODEL_ID", "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"
        ),
        MODEL_REVISION=os.getenv(
            "QWEN_MLX_MODEL_REVISION", "0d6bb6fe33f92d47a507e23b9148940e8366ab5b"
        ),
        TOKENIZERS_PARALLELISM="false",
        HF_HUB_DISABLE_PROGRESS_BARS="1",
    )
    sys.path.insert(0, str(ROOT))
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=18082, access_log=False)


if __name__ == "__main__":
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("This runner requires an Apple Silicon Mac.")
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    if action == "serve":
        serve()
    elif action == "status":
        print(
            json.dumps(
                status() or {"provider": "qwen", "status": "stopped"},
                ensure_ascii=False,
            )
        )
    elif action == "logs":
        print(LOG.read_text()[-12000:] if LOG.exists() else "No Mac model log yet.")
    elif action in {"up", "stop"}:
        with os.fdopen(
            os.open(DATA / "process.lock", os.O_CREAT | os.O_RDWR, 0o600), "w"
        ) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            (up if action == "up" else stop)()
    else:
        raise SystemExit("Usage: macos.py up|stop|status|logs|serve")
