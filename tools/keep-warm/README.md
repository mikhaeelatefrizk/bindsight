# Local keep-warm for the bindsight Streamlit demo

The previous keep-warm cron lived in `.github/workflows/keep-warm.yml`, but
GitHub Actions on this account is currently blocked by an upstream billing
issue. This folder is the no-payment, no-account local replacement.

## What's here

| File | Purpose |
|---|---|
| `keep_warm.py` | Pure stdlib Python — pings `bindsight.streamlit.app` once (or in a loop) |
| `setup_task_scheduler.bat` | One-time installer; registers a Windows Scheduled Task that runs `keep_warm.py` every 6 hours |
| `unregister_task_scheduler.bat` | Removes the scheduled task |

## One-time setup

1. **Verify Python is installed**: open Command Prompt, type `py --version` or `python --version`. If you see a version number, you're good. If not, install Python from https://www.python.org/downloads/ (any 3.x is fine — script uses only stdlib).
2. **Right-click `setup_task_scheduler.bat` → Run as administrator**.
3. You should see `SUCCESS: Task "bindsight Keep-warm" registered`.

That's it. Task Scheduler will now ping the URL every 6 hours, regardless of whether you're logged in (it runs in the background).

## Verify it's working

Open Task Scheduler (search "Task Scheduler" in the Start Menu), navigate to the Task Scheduler Library, and you should see **"bindsight Keep-warm"**. Right-click → Run to trigger immediately.

Or trigger from Command Prompt:

```cmd
schtasks /Run /TN "bindsight Keep-warm"
```

## Manual one-shot ping (sanity check)

```cmd
cd "C:\Users\mikha\Desktop\bioinformatics tool dev\tools\keep-warm"
py keep_warm.py
```

You should see:

```
[2026-05-15 12:34:56 UTC] https://bindsight.streamlit.app/  ->  HTTP 200  (OK)
```

## Caveats

- This pings from your local machine, so the Streamlit app only stays warm while your computer is on (or, more accurately, while Task Scheduler can run during the device's awake hours).
- The **Hugging Face Space mirror at https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight has no auto-sleep** and remains the durable demo URL regardless. The README in the bindsight repo already presents HF Space as primary; this script is a belt-and-suspenders for the Streamlit URL referenced in older outreach emails.

## To stop the keep-warm

Right-click `unregister_task_scheduler.bat` → Run as administrator.
