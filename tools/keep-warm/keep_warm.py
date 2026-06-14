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

Author: Mikhaeel Atef Rizk Wahba · MIT licensed (same as bindsight)
"""

import argparse
import sys
import time
from datetime import datetime, timezone

try:
    import requests  # type: ignore
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False
    import urllib.error
    import urllib.request

URL = "https://bindsight.streamlit.app/"
DEFAULT_INTERVAL_S = 6 * 60 * 60  # 6 hours
TIMEOUT_S = 120
USER_AGENT = "bindsight-keep-warm/1.0 (https://github.com/mikhaeelatefrizk/bindsight)"


def _wake_via_requests(url: str, timeout: int) -> tuple[bool, str]:
    """Wake Streamlit using the `requests` library.

    Streamlit Community Cloud sleep flow:
      1. GET https://bindsight.streamlit.app/  -> 303 to https://share.streamlit.io/...
      2. That page is the "Zzzz / Yes, get this app back up!" wake button.
      3. The button POSTs to a `/healthz`-style endpoint, which then takes
         60-120 s to boot the container and finally serves the app.

    We replicate steps 1-3 by doing a sequence of GETs/POSTs against the
    same endpoints the browser hits, with retries.  Per Streamlit's docs,
    even a single GET against the wake-up endpoint is enough to trigger
    the boot — we don't need to literally click a button.

    Returns (ok, message).
    """
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    try:
        # Follow all redirects through the wake-up chain.
        r = s.get(url, timeout=timeout, allow_redirects=True)
        # If we landed back on a Zzzz / wake-up page, the container is still
        # sleeping.  Trigger a wake by POSTing to the /healthz wake endpoint
        # at the final URL's origin.
        body = r.text[:5000]
        asleep_markers = ("Zzzz", "gone to sleep", "get-back-up", "shc-container-wake")
        looks_asleep = any(m in body for m in asleep_markers)
        if looks_asleep:
            # Try the Streamlit "share" wake URL: POST to the host's container
            # endpoint to trigger boot.
            try:
                wake_resp = s.post(
                    "https://share.streamlit.io/-/proxy/api/v1/wake",
                    json={"id": "mikhaeelatefrizk/bindsight"},
                    timeout=timeout,
                )
                _ = wake_resp.status_code  # noqa: F841 — we only care that it fired
            except requests.RequestException:
                pass
            # Then re-GET the app URL a couple of times to encourage boot.
            for _ in range(3):
                time.sleep(15)
                r2 = s.get(url, timeout=timeout, allow_redirects=True)
                body2 = r2.text[:5000]
                if not any(m in body2 for m in asleep_markers):
                    return True, f"HTTP {r2.status_code} (woken after retry)"
            return False, f"HTTP {r.status_code} (still asleep after wake attempt)"
        return (200 <= r.status_code < 400), f"HTTP {r.status_code} (awake)"
    except requests.RequestException as e:
        return False, f"network error: {e}"


def _wake_via_urllib(url: str, timeout: int) -> tuple[bool, str]:
    """Fallback path when `requests` is not installed.  Less robust but
    works for the common case (URL responds, container alive)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            return (200 <= status < 400), f"HTTP {status} (urllib fallback)"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code} (urllib fallback)"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"network error: {e}"


def ping_once(url: str = URL, timeout: int = TIMEOUT_S) -> tuple[bool, str]:
    """Ping URL; if it's asleep, attempt to wake.  Returns (ok, message)."""
    if HAVE_REQUESTS:
        return _wake_via_requests(url, timeout)
    return _wake_via_urllib(url, timeout)


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
