"""A stopped MPS daemon can leave its Unix socket behind."""

from pathlib import Path


def live_daemon_pid(pipe):
    pidfile = Path(pipe) / "nvidia-cuda-mps-control.pid"
    if not pidfile.exists():
        return None
    pid = int(pidfile.read_text().strip())
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.exists():
        return None
    if b"nvidia-cuda-mps-control" not in cmdline.read_bytes():
        raise ValueError("MPS PID file references an unrelated process")
    return pid
