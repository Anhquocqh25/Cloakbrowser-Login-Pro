from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes


TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def _process_family(root_pid: int) -> set[int]:
    if os.name != "nt":
        return {root_pid}
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        return {root_pid}
    parent_by_pid: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                parent_by_pid[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    family = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in parent_by_pid.items():
            if parent_pid in family and pid not in family:
                family.add(pid)
                changed = True
    return family


class WindowTitleTracker:
    """Prefix Chromium top-level window titles without touching page content."""

    def __init__(self, root_pid: int, profile_name: str) -> None:
        self.root_pid = int(root_pid)
        safe_name = " ".join(profile_name.split()).strip() or "Profile"
        self.prefix = f"[{safe_name}] · "
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "WindowTitleTracker":
        if os.name == "nt" and self._thread is None:
            self._thread = threading.Thread(
                target=self._run,
                name=f"browser-title-{self.root_pid}",
                daemon=True,
            )
            self._thread.start()
        return self

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        while not self._stop_event.wait(0.4):
            try:
                self._apply()
            except Exception:
                # Window discovery is cosmetic and must never stop the browser.
                pass

    def _apply(self) -> None:
        user32 = ctypes.windll.user32
        family = _process_family(self.root_pid)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        user32.SetWindowTextW.restype = wintypes.BOOL

        @callback_type
        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in family:
                return True
            class_name = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            if not class_name.value.startswith("Chrome_WidgetWin_"):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            title = title_buffer.value
            if title and not title.startswith(self.prefix):
                user32.SetWindowTextW(hwnd, f"{self.prefix}{title}")
            return True

        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows(visit, 0)
