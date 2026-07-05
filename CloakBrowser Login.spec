from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_dir = Path(SPEC).resolve().parent
cloak_datas, cloak_binaries, cloak_hidden = collect_all("cloakbrowser")

datas = [
    (str(project_dir / "ui" / "styles.qss"), "ui"),
    (str(project_dir / "assets" / "app_logo.png"), "assets"),
    (str(project_dir / "assets" / "flags"), "assets/flags"),
    (str(project_dir / "extensions" / "fingerprint_bookmarks"), "extensions/fingerprint_bookmarks"),
    *cloak_datas,
]

a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=[*cloak_binaries],
    datas=datas,
    hiddenimports=[*cloak_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CloakBrowser Login",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "assets" / "app_icon.ico"),
    version=str(project_dir / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CloakBrowser Login",
)
