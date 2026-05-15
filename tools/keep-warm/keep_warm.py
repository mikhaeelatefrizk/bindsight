"""
keep_warm.py — pings the bindsight Streamlit demo so it doesn't auto-sleep.

Background
----------
Streamlit Community Cloud's free tier auto-sleeps apps after a few days of
inactivity. The previous keep-warm cron lived in GitHub Actions
(.github/workflows/keep-warm.yml) but that workflow is currently disabled
because GitHub Actions on this account is blocked by an upstream billing
issue. This local script does the same thing without paying for anything.

Run modes
---------
* `python keep_warm.py` — pings once, prints status, exits.
* `python keep_warm.py --loop` — pings every 6 hours forever (useful when
  scheduled via Windows Task Scheduler running on system startup OR run in
  a leftover terminal).
* `python keep_warm.py --interval 300` — combine with --loop to set custom
  ping interval in seconds (default 21600 = 6 hours).

Setup as a Windows scheduled task (one-time)
--------------------------------------------
The file `setup_task_scheduler.bat` next to this script will register a
Windows Scheduled Task that runs `python keep_warm.py` once every 6 hours,
silently, regardless of whether you're logged in. Right-click that .bat,
choose "Run as administrator", and the task is registered. To remove,
run `unregister_task_scheduler.bat` the same way.

What this is NOT
----------------
This script is the user's machine pinging Streamlit Cloud. If your laptop
is asleep / off, no ping fires. The Hugging Face Space mirror at
https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight has no auto-sleep
and remains the durable demo URL regardless. This script just keeps the
secondary Streamlit URL warm for visitors who got the older link.

Author: Mikhaeel Atef Rizk · MIT licensed (same as bindsight)
"""

import argparse
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

URL = "https://bindsight.streamlit.app/"
DEFAULT_INTERVAL_S = 6 * 60 * 60  # 6 hours
TIMEOUT_S = 120
USER_AGENT = "bindsight-keep-warm/1.0 (https://github.com/mikhaeelatefrizk/bindsight)"


def ping_once(url: str = URL, timeout: int = TIMEOUT_S) -> tuple[bool, str]:
    """Hit the URL once. Returns (ok, message).

    Any 2xx, 3xx, or 4xx response counts as OK — the goal is to *touch* the
    Streamlit container and prevent the inactivity timer from sleeping it,
    not to fetch a successful body.  Streamlit's wake-up flow returns 3xx
    redirect chains and occasional 4xx during boot; those are still
    "the container is alive enough to respond" signals.  Only network
    timeouts / connection refusals count as real failures.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            ok = 200 <= status < 500
            return ok, f"HTTP {status}"
    except urllib.error.HTTPError as e:
        # Server returned a status code that urllib treated as an error.
        # Anything < 500 still means the container is alive.
        return e.code < 500, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"network error: {e}"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping the bindsight Streamlit demo to prevent auto-sleep.")
    parser.add_argument("--loop", action="store_true", help="Run forever, pinging every --interval seconds.")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S, help="Seconds between pings in --loop mode.")
    parser.add_argument("--url", default=URL, help="URL to ping (default: bindsight.streamlit.app).")
    args = parser.parse_args()

    if not args.loop:
        ok, msg = ping_once(args.url)
        print(f"[{stamp()}] {args.url}  ->  {msg}  ({'OK' if ok else 'FAIL'})")
        return 0 if ok else 1

    print(f"[{stamp()}] starting keep-warm loop, every {args.interval}s, target {args.url}")
    while True:
        ok, msg = ping_once(args.url)
        print(f"[{stamp()}] {args.url}  ->  {msg}  ({'OK' if ok else 'FAIL'})", flush=True)
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"[{stamp()}] interrupted; exiting.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
