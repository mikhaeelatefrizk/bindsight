# SPDX-License-Identifier: AGPL-3.0-or-later
# PyInstaller spec. Build through build.py so revision metadata is mandatory.
import os
import sys
from pathlib import Path

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / "companion/app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "companion/pins.json"), "companion"), (os.environ["BINDSIGHT_BUILD_INFO"], "companion")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "numpy", "pandas", "scipy", "bindsight"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [], name="BindsightCompanion", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=sys.platform not in {"win32", "darwin"})
if sys.platform == "darwin":
    app = BUNDLE(exe, name="Bindsight Companion.app", bundle_identifier="org.bindsight.companion", info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0", "CFBundleURLTypes": [{"CFBundleURLName": "Bindsight open workspace", "CFBundleURLSchemes": ["bindsight"]}]})
