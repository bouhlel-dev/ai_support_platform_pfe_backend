import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Dict

from fastapi import FastAPI, HTTPException
import uvicorn
from pydantic import BaseModel

import threading

app = FastAPI()

process = None
mode = None
started_at = None
last_exit_code = None
log_handle = None
log_file = Path("uploads/voice_agents.log")
lock = threading.Lock()

class StartRequest(BaseModel):
    mode: Literal["dev", "start"]
    env_vars: Dict[str, str]

def cleanup_orphans():
    import signal
    my_pid = os.getpid()
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == my_pid:
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'r') as cf:
                cmd = cf.read().replace(chr(0), ' ')
            # Kill any python process that looks like a voice agent
            if 'python' in cmd and ('run_voice_agents.py' in cmd or 'voice_agents.server' in cmd):
                # Extra check: if it's not our current 'process' tracking global
                # We'll kill it just to be safe.
                os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass

def _sync():
    global process, mode, started_at, last_exit_code, log_handle
    if process is not None:
        if process.poll() is not None:
            last_exit_code = process.returncode
            process = None
            mode = None
            started_at = None
            if log_handle:
                try: log_handle.close()
                except: pass
                log_handle = None

@app.post("/start")
def start_agent(req: StartRequest):
    global process, mode, started_at, log_handle
    with lock:
        _sync()
        if process is not None:
            raise HTTPException(409, "Already running")
            
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "a", encoding="utf-8")
        log_handle.write(f"\n\n[{datetime.now(timezone.utc).isoformat()}] Starting in {req.mode} mode\n")
        log_handle.write(f"[{datetime.now(timezone.utc).isoformat()}] Cleaning up orphans...\n")
        cleanup_orphans()
        log_handle.write(f"[{datetime.now(timezone.utc).isoformat()}] Starting subprocess: {sys.executable} run_voice_agents.py {req.mode}\n")
        log_handle.flush()
        
        env = os.environ.copy()
        env.update(req.env_vars)
        env["LIVEKIT_WORKER_PORT"] = "8090"
        
        process = subprocess.Popen(
            [sys.executable, "run_voice_agents.py", req.mode],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        mode = req.mode
        started_at = datetime.now(timezone.utc)
        return {"message": "started"}

@app.post("/stop")
def stop_agent():
    global process, mode, started_at, last_exit_code, log_handle
    _sync()
    if process is None:
        return {"message": "not running"}
    process.terminate()
    try:
        process.wait(timeout=5)
    except:
        process.kill()
        process.wait(timeout=5)
    last_exit_code = process.returncode
    process = None
    mode = None
    started_at = None
    if log_handle:
        try: log_handle.close()
        except: pass
        log_handle = None
    return {"message": "stopped"}

@app.get("/status")
def get_status():
    _sync()
    running = process is not None
    uptime = (datetime.now(timezone.utc) - started_at).total_seconds() if running and started_at else None
    return {
        "running": running,
        "pid": process.pid if running else None,
        "mode": mode,
        "started_at": started_at,
        "uptime_seconds": uptime,
        "last_exit_code": last_exit_code,
        "log_file": str(log_file)
    }

@app.get("/logs")
def get_logs(lines: int = 200):
    if not log_file.exists():
        return {"lines": []}
    data = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"lines": data[-lines:] if lines > 0 else []}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
