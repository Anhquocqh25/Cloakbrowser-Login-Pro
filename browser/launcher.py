from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from models.profile import Profile
from utils.browser_preferences import configure_duckduckgo
from utils.local_proxy_bridge import LocalProxyBridge
from utils.paths import profile_user_data_dir
from utils.startup_url import normalize_startup_url
from utils.window_title import WindowTitleTracker

try:
    from cloakbrowser import build_args as cloak_build_args
    from cloakbrowser import maybe_resolve_geoip
    from cloakbrowser.browser import seed_widevine_hint
    from cloakbrowser.download import ensure_binary
except ImportError:
    cloak_build_args = None
    maybe_resolve_geoip = None
    seed_widevine_hint = None
    ensure_binary = None


class BrowserLaunchError(RuntimeError):
    pass


class NativeBrowserProcess:
    """Lifecycle adapter for a browser started directly without Playwright/CDP."""

    is_native_process = True
    supports_sync = False

    def __init__(
        self,
        process: subprocess.Popen,
        proxy_bridge: LocalProxyBridge | None = None,
        title_tracker: WindowTitleTracker | None = None,
    ) -> None:
        self.process = process
        self.proxy_bridge = proxy_bridge
        self.title_tracker = title_tracker

    @property
    def pages(self) -> list:
        return []

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        try:
            if self.title_tracker is not None:
                self.title_tracker.close()
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            if self.proxy_bridge is not None:
                self.proxy_bridge.close()


def builtin_extension_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "extensions" / "fingerprint_bookmarks"


def find_google_chrome() -> Path | None:
    if os.name != "nt":
        return None
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _version_key(path: Path) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in path.parent.name.split("."))
    except ValueError:
        return (0,)


def ensure_windows_dxil() -> None:
    """Supply Dawn's DXC runtime from a locally installed Chrome/Edge."""
    if os.name != "nt" or ensure_binary is None:
        return
    binary_dir = Path(ensure_binary()).resolve().parent
    required_dlls = ("dxil.dll", "dxcompiler.dll")
    if all((binary_dir / name).exists() for name in required_dlls):
        return

    roots = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application",
    ]
    candidates = [
        version_dir
        for root in roots if root.exists()
        for version_dir in root.iterdir()
        if version_dir.is_dir() and all((version_dir / name).exists() for name in required_dlls)
    ]
    if candidates:
        source_dir = max(candidates, key=lambda item: _version_key(item / "dxil.dll"))
        for name in required_dlls:
            destination = binary_dir / name
            if not destination.exists():
                shutil.copy2(source_dir / name, destination)


def _extension_paths(extension_paths: list[str] | None) -> list[str]:
    selected = [str(builtin_extension_dir())] if extension_paths is None else extension_paths
    return list(dict.fromkeys(str(Path(item).resolve()) for item in selected))


def _start_process(
    executable: Path,
    args: list[str],
    name: str,
    proxy_bridge: LocalProxyBridge | None,
    profile_name: str,
) -> NativeBrowserProcess:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            [str(executable), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
        )
        time.sleep(0.5)
        if process.poll() is not None:
            raise BrowserLaunchError(f"{name} exited with code {process.returncode}.")
        title_tracker = WindowTitleTracker(process.pid, profile_name).start()
        return NativeBrowserProcess(process, proxy_bridge, title_tracker)
    except Exception:
        if proxy_bridge is not None:
            proxy_bridge.close()
        raise


def launch_browser(profile: Profile, extension_paths: list[str] | None = None) -> Any:
    if profile.browser_engine == "chrome":
        return launch_native_chrome(profile, extension_paths)
    return launch_cloak_clean(profile, extension_paths)


def launch_cloak_clean(profile: Profile, extension_paths: list[str] | None = None) -> NativeBrowserProcess:
    """Launch Cloak directly with fingerprint flags and no Playwright/CDP channel."""
    if any(item is None for item in (cloak_build_args, maybe_resolve_geoip, ensure_binary)):
        raise BrowserLaunchError(
            "Could not import cloakbrowser. Install dependencies with pip install -r requirements.txt"
        )

    ensure_windows_dxil()
    binary_path = Path(ensure_binary(profile.cloak_version or None)).resolve()
    data_dir = profile_user_data_dir(profile.id)
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_duckduckgo(data_dir)

    fingerprint_platform = (
        profile.platform if profile.platform in {"windows", "macos", "linux"} else "windows"
    )
    locale = profile.locale or None
    timezone = profile.timezone or None
    exit_ip: str | None = None
    proxy_bridge: LocalProxyBridge | None = None

    if profile.proxy:
        try:
            # Even with manual locale/timezone, resolve the real proxy exit IP so
            # Cloak's WebRTC fingerprint cannot accidentally expose the local IP.
            requested_timezone = None if profile.auto_geoip else timezone
            requested_locale = None if profile.auto_geoip else locale
            timezone, locale, exit_ip = maybe_resolve_geoip(
                True, profile.proxy, requested_timezone, requested_locale
            )
            if not exit_ip:
                raise RuntimeError("proxy exit IP could not be resolved")
            proxy_bridge = LocalProxyBridge(profile.proxy).start()
        except Exception as error:
            if proxy_bridge is not None:
                proxy_bridge.close()
            raise BrowserLaunchError(f"Could not prepare proxy fingerprint: {error}") from error

    extra_args = [
        f"--user-data-dir={data_dir}",
        f"--fingerprint={profile.fingerprint_seed}",
        f"--fingerprint-platform={fingerprint_platform}",
        f"--fingerprint-screen-width={profile.screen_width}",
        f"--fingerprint-screen-height={profile.screen_height}",
        f"--window-size={profile.screen_width},{profile.screen_height}",
        "--show-bookmarks-bar",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-search-engine-choice-screen",
        "--disable-session-crashed-bubble",
        "--disable-background-mode",
    ]
    if profile.user_agent.strip():
        extra_args.append(f"--user-agent={profile.user_agent.strip()}")
    if proxy_bridge is not None:
        extra_args.extend([
            f"--proxy-server={proxy_bridge.url}",
            "--proxy-bypass-list=localhost;127.0.0.1",
            f"--fingerprint-webrtc-ip={exit_ip}",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--disable-quic",
        ])
    headless = os.environ.get("CLOAK_LOGIN_HEADLESS", "0") == "1"
    if headless:
        extra_args.append("--headless=new")

    args = cloak_build_args(
        True,
        extra_args,
        timezone=timezone,
        locale=locale,
        headless=headless,
        extension_paths=_extension_paths(extension_paths),
    )
    try:
        args.append(normalize_startup_url(profile.startup_url) or "about:blank")
    except ValueError as error:
        if proxy_bridge is not None:
            proxy_bridge.close()
        raise BrowserLaunchError(str(error)) from error
    if seed_widevine_hint is not None:
        seed_widevine_hint(data_dir, binary_path)
    return _start_process(binary_path, args, "CloakBrowser", proxy_bridge, profile.name)


def launch_native_chrome(profile: Profile, extension_paths: list[str] | None = None) -> NativeBrowserProcess:
    """Launch installed Chrome directly without fingerprint emulation or CDP."""
    chrome_path = find_google_chrome()
    if chrome_path is None:
        raise BrowserLaunchError("Google Chrome is not installed or could not be found.")

    loaded_extensions = _extension_paths(extension_paths)
    data_dir = profile_user_data_dir(profile.id) / "chrome-native"
    configure_duckduckgo(data_dir)
    args = [
        f"--user-data-dir={data_dir}",
        f"--window-size={profile.screen_width},{profile.screen_height}",
        "--show-bookmarks-bar",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-search-engine-choice-screen",
        "--disable-session-crashed-bubble",
        "--disable-background-mode",
    ]
    if profile.locale:
        args.append(f"--lang={profile.locale}")
    if loaded_extensions:
        joined = ",".join(loaded_extensions)
        args.extend([f"--disable-extensions-except={joined}", f"--load-extension={joined}"])
    proxy_bridge: LocalProxyBridge | None = None
    if profile.proxy:
        try:
            proxy_bridge = LocalProxyBridge(profile.proxy).start()
            args.extend([
                f"--proxy-server={proxy_bridge.url}",
                "--proxy-bypass-list=localhost;127.0.0.1",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--disable-quic",
            ])
        except Exception as error:
            raise BrowserLaunchError(f"Could not start local proxy bridge: {error}") from error
    if os.environ.get("CLOAK_LOGIN_HEADLESS", "0") == "1":
        args.append("--headless=new")
    try:
        args.append(normalize_startup_url(profile.startup_url) or "about:blank")
    except ValueError as error:
        if proxy_bridge is not None:
            proxy_bridge.close()
        raise BrowserLaunchError(str(error)) from error
    return _start_process(chrome_path, args, "Google Chrome", proxy_bridge, profile.name)


def close_browser(context: Any) -> None:
    if context is not None:
        context.close()
