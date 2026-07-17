"""Small pystray adapter that keeps all Tk mutations on the Tk thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import tkinter as tk

from PIL import Image

try:
    import pystray
except ImportError:  # The desktop pet still starts and reports the missing tray.
    pystray = None


PYSTRAY_AVAILABLE = pystray is not None


def make_tray_icon(source: Image.Image, size: int = 64) -> Image.Image:
    """Fit the current pixel character into a transparent square tray icon."""

    source = source.convert("RGBA")
    bounds = source.getchannel("A").getbbox()
    subject = source.crop(bounds) if bounds else source
    maximum = max(16, int(size) - 6)
    subject.thumbnail((maximum, maximum), Image.Resampling.NEAREST)
    output = Image.new("RGBA", (int(size), int(size)), (0, 0, 0, 0))
    x = (output.width - subject.width) // 2
    y = (output.height - subject.height) // 2
    output.alpha_composite(subject, (x, y))
    return output


class SystemTrayController:
    """Own a tray icon while dispatching every application action through Tk."""

    def __init__(
        self,
        root: Any,
        image: Image.Image,
        *,
        is_hidden: Callable[[], bool],
        toggle_visibility: Callable[[], None],
        is_do_not_disturb: Callable[[], bool],
        toggle_do_not_disturb: Callable[[], None],
        is_paused: Callable[[], bool],
        toggle_pause: Callable[[], None],
        close_application: Callable[[], None],
        character_name: str = "桌宠",
        backend: Any = pystray,
    ) -> None:
        self.root = root
        self.image = make_tray_icon(image)
        self.is_hidden = is_hidden
        self.toggle_visibility = toggle_visibility
        self.is_do_not_disturb = is_do_not_disturb
        self.toggle_do_not_disturb = toggle_do_not_disturb
        self.is_paused = is_paused
        self.toggle_pause = toggle_pause
        self.close_application = close_application
        self.character_name = character_name.strip() or "桌宠"
        self.backend = backend
        self.icon: Any | None = None

    @property
    def available(self) -> bool:
        return self.backend is not None

    @property
    def running(self) -> bool:
        return self.icon is not None

    def _dispatch(self, callback: Callable[[], None]) -> None:
        try:
            self.root.after(0, callback)
        except (RuntimeError, OSError, tk.TclError):
            return

    def start(self) -> bool:
        if not self.available or self.icon is not None:
            return self.icon is not None
        backend = self.backend
        menu = backend.Menu(
            backend.MenuItem(
                lambda _item: "显示桌宠" if self.is_hidden() else "隐藏桌宠",
                lambda _icon, _item: self._dispatch(self.toggle_visibility),
                default=True,
            ),
            backend.MenuItem(
                "专注 / 勿扰模式",
                lambda _icon, _item: self._dispatch(self.toggle_do_not_disturb),
                checked=lambda _item: self.is_do_not_disturb(),
            ),
            backend.MenuItem(
                lambda _item: "继续动画" if self.is_paused() else "暂停动画",
                lambda _icon, _item: self._dispatch(self.toggle_pause),
            ),
            backend.Menu.SEPARATOR,
            backend.MenuItem(
                "退出 LIFE-Mind",
                lambda _icon, _item: self._dispatch(self.close_application),
            ),
        )
        self.icon = backend.Icon(
            "life-mind-pet",
            self.image,
            f"LIFE-Mind · {self.character_name}",
            menu,
        )
        try:
            self.icon.run_detached()
        except Exception:
            self.icon = None
            return False
        return True

    def update_menu(self) -> None:
        if self.icon is None:
            return
        try:
            self.icon.update_menu()
        except (AttributeError, RuntimeError, OSError):
            return

    def stop(self) -> None:
        icon, self.icon = self.icon, None
        if icon is None:
            return
        try:
            icon.stop()
        except (AttributeError, RuntimeError, OSError):
            return


__all__ = ("PYSTRAY_AVAILABLE", "SystemTrayController", "make_tray_icon")
