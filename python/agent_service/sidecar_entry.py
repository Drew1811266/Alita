from __future__ import annotations

import argparse
import ctypes
import os
import threading
import time

import uvicorn


def _watch_parent_process(parent_pid: int | None) -> None:
    if not parent_pid:
        return

    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        handle = kernel32.OpenProcess(synchronize, False, parent_pid)
        if not handle:
            return

        def wait_for_windows_parent() -> None:
            try:
                kernel32.WaitForSingleObject(handle, infinite)
                os._exit(0)
            finally:
                kernel32.CloseHandle(handle)

        threading.Thread(target=wait_for_windows_parent, daemon=True).start()
        return

    def poll_parent() -> None:
        while True:
            try:
                os.kill(parent_pid, 0)
            except OSError:
                os._exit(0)
            time.sleep(1)

    threading.Thread(target=poll_parent, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, default=None)
    args = parser.parse_args()
    _watch_parent_process(args.parent_pid)

    uvicorn.run(
        "agent_service.app:app",
        host="127.0.0.1",
        port=8765,
        log_level="info",
    )


if __name__ == "__main__":
    main()
