# SPDX-License-Identifier: AGPL-3.0-or-later
"""Packaged GUI entrypoint and offline CI verification modes."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from companion import wsl
from companion.core import (
    PINS,
    Cancelled,
    Installer,
    SetupError,
    app_directory,
    application_lock,
    embedded_revision,
    platform_key,
    source_checksum,
    validate_release,
    verify_source,
)
from companion.desktop import install_launcher, open_browser
from companion.protocol import OPEN_URI, existing_workspace, validate_open_uri


def self_test() -> dict[str, Any]:
    """Check bundled resources/Tcl and policy without GUI, network or installation."""
    import tkinter

    revision = embedded_revision()
    key = platform_key()
    tcl = tkinter.Tcl()
    return {
        "ok": True,
        "revision": revision,
        "platform": key,
        "uv_version": PINS["uv_version"],
        "uv_sha256": PINS["artifacts"][key]["sha256"],
        "python_version": PINS["python_version"],
        "tcl": tcl.eval("info patchlevel"),
        "network_requests": 0,
        "packages_installed": 0,
        "gui_created": False,
    }


def run_gui() -> int:
    """Present the install approval and retain a visible log while the app runs."""
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    window = tk.Tk()
    window.title("Bindsight — local research workspace")
    window.geometry("780x730" if sys.platform == "win32" else "760x590")
    window.minsize(620, 480)
    root = app_directory()
    messages: queue.Queue[tuple[str, Any]] = queue.Queue()
    cancel = threading.Event()
    worker: threading.Thread | None = None
    closing = False
    current_url: str | None = None
    wsl_buttons: list[ttk.Button] = []
    try:
        revision = embedded_revision()
        platform_key()
    except SetupError as exc:
        messagebox.showerror("Companion unavailable", str(exc), parent=window)
        window.destroy()
        return 1
    already_running = existing_workspace(root, revision)
    if already_running:
        open_browser(already_running)
        window.destroy()
        return 0
    frame = ttk.Frame(window, padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Bindsight on this computer", font=("TkDefaultFont", 18, "bold")).pack(
        anchor="w"
    )
    ttk.Label(
        frame, text="Set up once. Open your research workspace in your browser.", wraplength=700
    ).pack(anchor="w", pady=(6, 12))
    ttk.Label(
        frame,
        text="Setup downloads a private Python runtime and the CPU analysis packages. It needs internet and at least 4 GB free storage. No administrator access or existing Python is required. Optional GPU tools need supported NVIDIA hardware; the local workspace checks readiness before offering their separate installation.",
        wraplength=700,
        justify="left",
    ).pack(anchor="w")
    ttk.Label(frame, text=f"Files and logs: {root}", wraplength=700).pack(anchor="w", pady=(8, 10))
    status = tk.StringVar(value="Nothing is downloaded until you approve setup.")
    ttk.Label(frame, textvariable=status, wraplength=700).pack(anchor="w", pady=(5, 8))
    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x", pady=(0, 10))
    log = scrolledtext.ScrolledText(frame, height=13, wrap="word", state="disabled")
    log.pack(fill="both", expand=True)
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 0))

    def report(message: str) -> None:
        messages.put(("log", message))

    def set_busy(busy: bool) -> None:
        setup_button.configure(state="disabled" if busy else "normal")
        for button in wsl_buttons:
            button.configure(state="disabled" if busy else "normal")
        stop_button.configure(state="normal" if busy else "disabled")
        if busy:
            progress.start()
        else:
            progress.stop()

    def start(approved: bool) -> None:
        nonlocal worker
        if worker and worker.is_alive():
            return
        cancel.clear()
        set_busy(True)
        status.set("Starting the local workspace…" if not approved else "Setting up Bindsight…")

        def work() -> None:
            try:
                with application_lock(root):
                    logs = root / "logs"
                    logs.mkdir(exist_ok=True)
                    with (logs / f"companion-{time.strftime('%Y%m%d-%H%M%S')}.log").open(
                        "a", encoding="utf-8"
                    ) as stream:

                        def emit(message: str) -> None:
                            stream.write(message + "\n")
                            stream.flush()
                            report(message)

                        installer = Installer(root, revision, emit, cancel)
                        record = installer.current()
                        if record is None:
                            record = installer.install(approved=approved)
                            try:
                                shortcut = install_launcher(root)
                                if shortcut:
                                    emit(f"Installed launcher: {shortcut}")
                            except (OSError, SetupError) as exc:
                                emit(
                                    f"Workspace installed; launcher shortcut needs attention: {exc}"
                                )
                        installer.launch(record, lambda url: messages.put(("browser", url)))
                messages.put(("done", "The local workspace stopped."))
            except Cancelled as exc:
                messages.put(("done", str(exc)))
            except Exception as exc:
                report(f"Setup/application error: {type(exc).__name__}: {exc}")
                messages.put(("error", str(exc)))

        worker = threading.Thread(target=work, daemon=True)
        worker.start()

    def start_wsl(action: str) -> None:
        nonlocal worker
        if worker and worker.is_alive():
            return
        if action == "workspace" and not messagebox.askokcancel(
            "Set up a separate Linux workspace?",
            "Check supported WSL2 Ubuntu and NVIDIA hardware, then download the matching Linux companion and private CPU packages into your Linux user folder?\n\nWindows analyses stay in the Windows workspace. GPU packages and models require a separate approval in the Linux browser workspace. This does not install or reconfigure Windows Linux support.",
            parent=window,
        ):
            return
        if action == "os" and not messagebox.askokcancel(
            "Ask Windows to install Linux support?",
            "Windows will request administrator approval to install WSL and Ubuntu 24.04. This changes optional Windows components and may require a restart. Bindsight will not restart the computer.\n\nAfter installation, open Ubuntu from Start and finish its username/password setup. This is separate from Bindsight's private CPU setup and does not make an unsupported GPU eligible.",
            parent=window,
        ):
            return
        cancel.clear()
        set_busy(True)
        status.set("Checking Linux workspace prerequisites…")

        def work() -> None:
            logs = root / "logs"
            try:
                logs.mkdir(parents=True, exist_ok=True)
                with (logs / f"wsl-{time.strftime('%Y%m%d-%H%M%S')}.log").open(
                    "a", encoding="utf-8"
                ) as stream:

                    def emit(message: str) -> None:
                        stream.write(message + "\n")
                        stream.flush()
                        report(message)

                    if action == "os":
                        result = wsl.install_prerequisites(approved=True)
                        emit(result["message"])
                        messages.put(("done", result["message"]))
                    elif action == "check":
                        result = wsl.readiness()
                        messages.put(("wsl_state", result))
                    else:
                        with application_lock(root):
                            owner = uuid.uuid4().hex
                            marker = root / "running.json"

                            def opened(url: str) -> None:
                                marker.write_text(
                                    json.dumps({"revision": revision, "url": url, "owner": owner})
                                    + "\n",
                                    encoding="utf-8",
                                )
                                messages.put(("browser", url))

                            try:
                                wsl.launch(root, revision, emit, cancel, opened)
                            finally:
                                if (
                                    marker.is_file()
                                    and json.loads(marker.read_text()).get("owner") == owner
                                ):
                                    marker.unlink()
                        messages.put(("done", "The separate Linux workspace stopped."))
            except Cancelled as exc:
                messages.put(("done", str(exc)))
            except Exception as exc:
                report(f"Linux setup error: {type(exc).__name__}: {exc}")
                messages.put(("error", str(exc)))

        worker = threading.Thread(target=work, daemon=True)
        worker.start()

    def approve_setup() -> None:
        if messagebox.askokcancel(
            "Set up Bindsight?",
            "Download the verified Bindsight release, private Python and CPU packages into your app-data folder, create a personal launcher, and register the bindsight://open launch link for your user account?\n\nYour system Python and security settings will not be changed. GPU models are not included.",
            parent=window,
        ):
            start(True)

    def stop() -> None:
        cancel.set()
        status.set("Stopping owned processes; please wait…")
        stop_button.configure(state="disabled")

    def close() -> None:
        nonlocal closing
        if worker and worker.is_alive():
            if not messagebox.askokcancel(
                "Stop Bindsight?",
                "Closing stops this local workspace and any work it is running. Saved files remain on this computer.",
                parent=window,
            ):
                return
            closing = True
            stop()
        else:
            window.destroy()

    def drain() -> None:
        nonlocal current_url
        while not messages.empty():
            kind, value = messages.get_nowait()
            if kind == "log":
                log.configure(state="normal")
                log.insert("end", value + "\n")
                if int(log.index("end-1c").split(".")[0]) > 3000:
                    log.delete("1.0", "1000.0")
                log.see("end")
                log.configure(state="disabled")
            elif kind == "browser":
                current_url = value
                status.set("Bindsight is running. Keep this window open.")
                progress.stop()
                browser_button.configure(state="normal")
                if not open_browser(value):
                    report(f"Open this local address in your browser: {value}")
            elif kind == "wsl_state":
                set_busy(False)
                message = (
                    "Linux prerequisites are available. Open the separate Linux workspace to continue."
                    if value["ready"]
                    else " ".join(value["blockers"])
                )
                status.set(message)
                report(message)
            else:
                set_busy(False)
                current_url = None
                status.set(value)
                setup_button.configure(state="normal", text="Retry / open Bindsight")
                stop_button.configure(state="disabled")
                browser_button.configure(state="disabled")
                if kind == "error":
                    messagebox.showerror(
                        "Bindsight could not finish",
                        value
                        + "\n\nThe log above contains the actual failure. You can retry; no incomplete installation is marked ready.",
                        parent=window,
                    )
        if closing and worker and not worker.is_alive():
            window.destroy()
            return
        window.after(150, drain)

    setup_button = ttk.Button(buttons, text="Set up Bindsight", command=approve_setup)
    setup_button.pack(side="left")
    browser_button = ttk.Button(
        buttons,
        text="Open browser",
        state="disabled",
        command=lambda: open_browser(current_url) if current_url else None,
    )
    browser_button.pack(side="left", padx=8)
    stop_button = ttk.Button(buttons, text="Stop / cancel", state="disabled", command=stop)
    stop_button.pack(side="right")
    ttk.Button(buttons, text="Close", command=close).pack(side="right", padx=8)
    if sys.platform == "win32":
        linux = ttk.LabelFrame(frame, text="Optional GPU workflow in Linux", padding=10)
        linux.pack(fill="x", pady=(12, 0))
        ttk.Label(
            linux,
            text="Requires WSL2 Ubuntu and a supported nominal 16 GB NVIDIA GPU (at least 15,360 MiB reported). This opens a separate Linux workspace; Windows runs are kept in Windows. Stop this workspace first to switch to GPU workspace.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w")
        actions = ttk.Frame(linux)
        actions.pack(fill="x", pady=(7, 0))
        for label, action in [
            ("Check readiness", "check"),
            ("GPU workspace", "workspace"),
            ("Install Windows Linux support…", "os"),
        ]:
            button = ttk.Button(actions, text=label, command=partial(start_wsl, action))
            button.pack(side="left", padx=(0, 5))
            wsl_buttons.append(button)
        ttk.Button(
            linux,
            text="Official Windows setup guide",
            command=lambda: open_browser(wsl.GUIDANCE_URL),
        ).pack(anchor="w", pady=(5, 0))
    window.protocol("WM_DELETE_WINDOW", close)
    if sys.platform == "darwin":

        def launch_url(*urls: str) -> None:
            if urls != (OPEN_URI,):
                report("Unsupported launch link rejected.")
            elif current_url:
                open_browser(current_url)
            elif not worker or not worker.is_alive():
                start(False)

        window.createcommand("::tk::mac::LaunchURL", launch_url)
    window.after(150, drain)
    # Reopening a completed installation runs local code only; no downloads.
    try:
        installed = Installer(root, revision, report, cancel).current()
    except (OSError, ValueError, SetupError):
        installed = None
    if installed:
        window.after(250, lambda: start(False))
    window.mainloop()
    return 0


def main() -> int:
    """Dispatch offline CI checks before creating the desktop window."""
    parser = argparse.ArgumentParser(description="Bindsight companion")
    parser.add_argument("uri", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--setup-approved", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cancel-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-existing-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.uri is not None:
        try:
            validate_open_uri(args.uri, sys.argv[1:])
        except SetupError as exc:
            parser.error(str(exc))
    if args.smoke_existing_root:
        if not args.self_test_output or args.uri is not None:
            parser.error("Existing-install smoke requires an output file and no launch URI")
        from companion.validation import smoke_existing

        try:
            result = smoke_existing(args.smoke_existing_root)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        args.self_test_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0 if result["ok"] else 1
    if args.headless:
        if not args.setup_approved or args.uri is not None or sys.platform != "linux":
            parser.error("The approved headless setup is reserved for the Linux WSL bridge")
        cancel = threading.Event()

        def emit(event: str, **data: str) -> None:
            print(json.dumps({"event": event, **data}), flush=True)

        if args.cancel_file:

            def monitor() -> None:
                while not cancel.wait(0.15):
                    if args.cancel_file.exists():
                        cancel.set()

            threading.Thread(target=monitor, daemon=True).start()
        try:
            root = app_directory()
            with application_lock(root):
                logs = root / "logs"
                logs.mkdir(exist_ok=True)
                with (logs / f"headless-{time.strftime('%Y%m%d-%H%M%S')}.log").open(
                    "a", encoding="utf-8"
                ) as stream:

                    def report(message: str) -> None:
                        stream.write(message + "\n")
                        stream.flush()
                        emit("log", message=message)

                    installer = Installer(root, embedded_revision(), report, cancel)
                    record = installer.current() or installer.install(approved=True)
                    installer.launch(record, lambda url: emit("browser", url=url))
            return 0
        except Cancelled:
            emit("log", message="Linux workspace stopped; saved files were retained.")
            return 0
        except Exception as exc:
            emit("log", message=f"Linux workspace error: {type(exc).__name__}: {exc}")
            return 1
    if args.self_test or args.verify_only:
        try:
            result = self_test()
            if args.verify_only:
                if not all([args.source, args.release, args.checksums]):
                    parser.error("--verify-only requires --source, --release and --checksums")
                validate_release(json.loads(args.release.read_text()), result["revision"])
                members = verify_source(
                    args.source, source_checksum(args.checksums.read_text()), result["revision"]
                )
                result["source_members_verified"] = len(members)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        serialized = json.dumps(result, indent=2) + "\n"
        if args.self_test_output:
            args.self_test_output.write_text(serialized, encoding="utf-8", newline="\n")
        if sys.stdout is not None:
            print(serialized)
        return 0 if result["ok"] else 1
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
