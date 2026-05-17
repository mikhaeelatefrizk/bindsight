"""
poll_helmholtz_url.py — checks the Helmholtz Munich AIH Google Form URL on a
schedule and writes a status line.  When the URL stops returning 404 (i.e.,
Marr fixed it server-side OR someone re-shared the form), it writes a banner
into a "POLL_STATUS.txt" file that can be checked manually.

This is a self-contained passive monitor; it does NOT email/notify, because
the user already gets a Proton-mail notification when Marr replies.  The
poll is a redundancy that catches the case where Marr fixes the URL silently
without sending a fresh email.

Run manually: `python poll_helmholtz_url.py`        (one-shot)
Run in loop:  `python poll_helmholtz_url.py --loop` (every 30 minutes)

To wire into Task Scheduler, similar pattern to keep_warm.py.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests  # type: ignore
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False
    import urllib.error
    import urllib.request

URL = "https://docs.google.com/forms/d/e/1FAIpQLScCYGsRATz41mSJsw-Pp8nZ1mQvpZ1riouNl9x8rf4Aq-CG0Q/viewform"
DEFAULT_INTERVAL_S = 30 * 60  # 30 minutes
STATUS_FILE = Path(__file__).resolve().parent / "POLL_STATUS.txt"

USER_AGENT = "bindsight-helmholtz-poller/1.0 (https://github.com/mikhaeelatefrizk/bindsight)"


def check_once(url: str = URL, timeout: int = 30) -> tuple[bool, int, str]:
    """Returns (is_alive, http_status, summary).

    is_alive == True when the URL returns 200 AND the body does NOT contain
    Google Drive's "file not found" boilerplate.
    """
    headers = {"User-Agent": USER_AGENT}
    if HAVE_REQUESTS:
        try:
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            body = r.text[:4000]
        except requests.RequestException as e:
            return False, 0, f"network error: {e}"
        status = r.status_code
    else:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                body = resp.read(4000).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return False, e.code, f"HTTPError {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return False, 0, f"network error: {e}"

    is_404 = "Page Not Found" in body or "the file you have requested does not exist" in body
    is_alive = (status == 200) and not is_404
    summary = "ALIVE" if is_alive else ("404 (form still not found)" if is_404 else f"HTTP {status} (unexpected)")
    return is_alive, status, summary


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def write_status(alive: bool, status: int, summary: str) -> None:
    line = f"[{stamp()}] alive={alive} http={status} {summary}\n"
    # Append to a rolling log AND overwrite the headline file
    log = STATUS_FILE.with_name("POLL_LOG.txt")
    log.touch(exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(line)
    headline = "🎉 FORM IS ALIVE — submit it!" if alive else f"⏳ still broken: {summary}"
    STATUS_FILE.write_text(f"{headline}\nlast check: {stamp()}\nfull log: {log.name}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll Helmholtz Munich AIH Google Form URL for availability.")
    parser.add_argument("--loop", action="store_true", help="Run forever, every --interval seconds.")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S, help="Seconds between polls in --loop mode.")
    parser.add_argument("--url", default=URL, help="URL to poll.")
    args = parser.parse_args()

    if not args.loop:
        alive, status, summary = check_once(args.url)
        write_status(alive, status, summary)
        print(f"[{stamp()}] alive={alive} http={status} {summary}")
        return 0 if alive else 1

    print(f"[{stamp()}] starting Helmholtz form poll, every {args.interval}s")
    last_alive = False
    while True:
        alive, status, summary = check_once(args.url)
        write_status(alive, status, summary)
        if alive and not last_alive:
            print(f"[{stamp()}] 🎉 FORM JUST BECAME ALIVE — go submit it!", flush=True)
        else:
            print(f"[{stamp()}] alive={alive} http={status} {summary}", flush=True)
        last_alive = alive
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
