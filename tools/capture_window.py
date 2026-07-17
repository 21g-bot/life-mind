"""List or capture a Windows top-level window without changing its state."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageGrab


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    user32.SetProcessDPIAware()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def windows() -> list[tuple[int, str, tuple[int, int, int, int]]]:
    found: list[tuple[int, str, tuple[int, int, int, int]]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            found.append((hwnd, title.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found


def capture(hwnd: int) -> Image.Image:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            raise RuntimeError("PrintWindow failed")
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
        ):
            raise RuntimeError("GetDIBits failed")
        return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).copy()
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def capture_from_screen(hwnd: int) -> Image.Image:
    """Capture a hardware-accelerated window after bringing it to the foreground."""
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time_to_settle_ms = 80
    ctypes.windll.kernel32.Sleep(time_to_settle_ms)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    return ImageGrab.grab(
        bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
    ).convert("RGBA")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--title")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    matches = windows()
    if args.list:
        for hwnd, title, rect in matches:
            print(f"{hwnd}\t{rect}\t{title}")
    if args.title:
        selected = [entry for entry in matches if args.title.casefold() in entry[1].casefold()]
        if not selected:
            raise SystemExit(f"No visible window contains title: {args.title}")
        if not args.output:
            raise SystemExit("--output is required with --title")
        hwnd, title, rect = selected[0]
        image = capture(hwnd)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.output)
        print(f"Captured {title!r} {rect} -> {args.output} {image.size}")


if __name__ == "__main__":
    main()
