# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install a per-user launcher without administrator privileges or policy changes."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from companion.core import SetupError, external_environment, external_libraries, inside


def open_browser(url: str) -> bool:
    """Open the default browser without leaking bundled library paths to it."""
    if sys.platform == "win32":
        with external_libraries():
            return webbrowser.open(url)
    executable = "/usr/bin/open" if sys.platform == "darwin" else shutil.which("xdg-open")
    if not executable:
        return False
    try:
        subprocess.Popen(
            [executable, url],
            env=external_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def register_macos_bundle(target: Path) -> None:
    """Ask Launch Services to register the copied app's declared URL scheme."""
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    services = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
    create = core.CFURLCreateFromFileSystemRepresentation
    create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    create.restype = ctypes.c_void_p
    core.CFRelease.argtypes = [ctypes.c_void_p]
    register = services.LSRegisterURL
    register.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    register.restype = ctypes.c_int32
    data = os.fsencode(target)
    url = create(None, data, len(data), True)
    if not url:
        raise SetupError("macOS could not create the installed app's registration URL.")
    try:
        if register(url, True) != 0:
            raise SetupError("macOS did not register the installed app's launch link.")
    finally:
        core.CFRelease(url)


def register_windows_protocol(target: Path) -> None:
    """Register only the fixed open action under the current Windows user."""
    if sys.platform != "win32":
        raise SetupError("Windows protocol registration requires Windows.")
    import winreg

    prefix = r"Software\Classes\bindsight"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, prefix) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Bindsight research workspace")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, prefix + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{target}" "%1"')


def install_launcher(root: Path) -> Path | None:
    """Persist the packaged application and register a user-owned launch entry."""
    if not getattr(sys, "frozen", False):
        return None
    launchers = inside(root, root / "launcher")
    launchers.mkdir(exist_ok=True)
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        bundle = executable.parents[2]
        if bundle.suffix != ".app":
            raise SetupError("The macOS companion must be launched from its app bundle.")
        target = launchers / "Bindsight Companion.app"
        if bundle != target.resolve():
            shutil.copytree(bundle, target, dirs_exist_ok=True, symlinks=True)
        applications = Path.home() / "Applications"
        applications.mkdir(exist_ok=True)
        shortcut = applications / "Bindsight Companion.app"
        if not shortcut.exists():
            shortcut.symlink_to(target, target_is_directory=True)
        elif shortcut.resolve() != target.resolve():
            raise SetupError(
                "A different Bindsight app already occupies the Applications shortcut."
            )
        register_macos_bundle(target)
        return shortcut
    target = launchers / ("BindsightCompanion.exe" if os.name == "nt" else "BindsightCompanion")
    if executable != target.resolve():
        shutil.copy2(executable, target)
    target.chmod(0o700)
    if sys.platform == "win32":
        register_windows_protocol(target)
        directory = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
        directory.mkdir(parents=True, exist_ok=True)
        shortcut = directory / "Bindsight.lnk"
        env = dict(
            external_environment(),
            BINDSIGHT_LINK_PATH=str(shortcut),
            BINDSIGHT_LINK_TARGET=str(target),
        )
        script = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:BINDSIGHT_LINK_PATH); $s.TargetPath=$env:BINDSIGHT_LINK_TARGET; $s.Description='Open the local Bindsight research workspace'; $s.Save()"
        # Constant PowerShell code; paths are data in the child environment.
        # No ExecutionPolicy switch or elevation; protocol association above is per user.
        powershell = (
            Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        with external_libraries():
            result = subprocess.run(
                [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                env=env,
                check=False,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        if result.returncode or not shortcut.is_file():
            raise SetupError(
                f"The Start menu shortcut could not be created. The installed app remains at {target}."
            )
        return shortcut
    applications = (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "applications"
    )
    applications.mkdir(parents=True, exist_ok=True)
    if any(char in str(target) for char in "\r\n"):
        raise SetupError("A launcher path cannot contain line breaks.")
    quoted = (
        str(target)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    shortcut = applications / "bindsight.desktop"
    shortcut.write_text(
        f'[Desktop Entry]\nType=Application\nName=Bindsight\nComment=Local research workspace\nExec="{quoted}" %u\nTerminal=false\nCategories=Science;\nMimeType=x-scheme-handler/bindsight;\n',
        encoding="utf-8",
        newline="\n",
    )
    shortcut.chmod(0o700)
    subprocess.run(
        ["xdg-mime", "default", shortcut.name, "x-scheme-handler/bindsight"],
        check=True,
        capture_output=True,
        env=external_environment(),
    )
    return shortcut
