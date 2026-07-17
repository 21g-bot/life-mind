"""Small user-facing room: mood, affection and selected diary pages only."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from life_mind.mind import MindEngine


ROOM_BG = "#fff8e7"
CARD_BG = "#fffdf6"
INK = "#3d2b22"
MUTED = "#806b5d"
GOLD = "#d99624"
SUN = "#f6c453"
ROSE = "#d77b72"


class PrivateRoomWindow:
    """A deliberately narrow window into the character, not a mind dashboard."""

    def __init__(
        self,
        parent: tk.Misc,
        mind: MindEngine,
        *,
        character_name: str = "桌宠",
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.mind = mind
        self.character_name = character_name.strip() or "桌宠"
        self.on_close = on_close
        self.window = tk.Toplevel(parent)
        self.window.title(f"{self.character_name}的个人房间")
        self.window.geometry("420x560")
        self.window.minsize(420, 520)
        self.window.configure(bg=ROOM_BG)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.snapshot: dict[str, object] = {}
        self._render()

    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        if self.exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def close(self) -> None:
        if self.exists():
            self.window.destroy()
        if self.on_close:
            self.on_close()

    def _clear(self) -> None:
        for child in self.window.winfo_children():
            child.destroy()

    def _header(self, subtitle: str) -> None:
        header = tk.Frame(self.window, bg=INK, height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text=f"{self.character_name}的小房间",
            bg=INK,
            fg="#fff7df",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w", padx=18, pady=(8, 0))
        tk.Label(
            header,
            text=subtitle,
            bg=INK,
            fg="#e8d7bd",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=18)

    def _card(self, parent: tk.Misc, title: str, *, expand: bool = False) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD_BG, highlightbackground="#ead9bd", highlightthickness=1)
        frame.pack(fill="both" if expand else "x", expand=expand, padx=14, pady=5)
        tk.Label(
            frame,
            text=title,
            bg=CARD_BG,
            fg=GOLD,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w", padx=14, pady=(9, 3))
        return frame

    def _render(self) -> None:
        self._clear()
        if self.mind.room_locked():
            self._render_locked()
        else:
            self._render_room()

    def _render_locked(self) -> None:
        self._header("她暂时把房间合上了")
        card = self._card(self.window, "房间已锁定", expand=True)
        tk.Label(card, text="◇", bg=CARD_BG, fg=GOLD, font=("Georgia", 46)).pack(
            pady=(68, 8)
        )
        tk.Label(
            card,
            text="这里的一键锁定只是视觉遮挡，\n不会代替 Windows 账户加密。",
            bg=CARD_BG,
            fg=MUTED,
            justify="center",
            font=("Microsoft YaHei UI", 9),
        ).pack(pady=8)
        tk.Button(
            card,
            text="解锁并查看",
            command=self._unlock,
            bg=SUN,
            fg=INK,
            activebackground="#ffd978",
            relief="flat",
            padx=22,
            pady=8,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(pady=(14, 8))
        tk.Button(card, text="关闭", command=self.close, relief="flat", bg=CARD_BG).pack()

    def _meter(
        self,
        parent: tk.Misc,
        title: str,
        value: float,
        label: str,
        color: str,
    ) -> None:
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill="x", padx=14, pady=(4, 2))
        tk.Label(
            row,
            text=title,
            bg=CARD_BG,
            fg=INK,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            row,
            text=f"{max(0.0, min(1.0, value)):.0%} · {label}",
            bg=CARD_BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")
        meter = tk.Canvas(parent, height=10, bg="#efe5d5", highlightthickness=0)
        meter.pack(fill="x", padx=14, pady=(1, 8))

        def paint(_event=None) -> None:
            meter.delete("all")
            width = max(1, meter.winfo_width())
            meter.create_rectangle(
                0,
                0,
                round(width * max(0.0, min(1.0, value))),
                10,
                fill=color,
                outline="",
            )

        meter.bind("<Configure>", paint)

    def _render_room(self) -> None:
        self.snapshot = self.mind.public_room_snapshot()
        mood = dict(self.snapshot["mood"])
        affection = dict(self.snapshot["affection"])
        self._header("只留下她愿意让你看到的部分")

        status = self._card(self.window, "现在的她")
        self._meter(status, "心情", float(mood["value"]), str(mood["label"]), SUN)
        self._meter(
            status,
            "好感度",
            float(affection["value"]),
            str(affection["label"]),
            ROSE,
        )

        journal = self._card(self.window, "重要日记", expand=True)
        entries = [dict(item) for item in self.snapshot["important_journal"]]
        text = tk.Text(
            journal,
            height=8,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            bg=CARD_BG,
            fg=INK,
            relief="flat",
            padx=8,
            pady=4,
        )
        text.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        if entries:
            for entry in entries:
                text.insert(tk.END, f"{entry['day']}\n", "date")
                text.insert(tk.END, f"{entry['content']}\n\n")
        else:
            text.insert(
                tk.END,
                "她暂时没有想公开的重要日记。\n\n"
                "不是每一天、每个想法都会变成可以查看的记录。",
            )
        text.tag_configure("date", foreground=GOLD, font=("Microsoft YaHei UI", 10, "bold"))
        text.configure(state="disabled")

        tk.Label(
            self.window,
            text="未公开的想法、关系细节和变化过程仍然属于她自己。",
            bg=ROOM_BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(pady=(1, 3))
        footer = tk.Frame(self.window, bg=ROOM_BG)
        footer.pack(fill="x", padx=14, pady=(0, 10))
        tk.Button(footer, text="刷新", command=self._render, relief="flat", bg="#efe3cf").pack(
            side="left"
        )
        tk.Button(
            footer,
            text="一键锁定",
            command=self._lock,
            relief="flat",
            bg=INK,
            fg="white",
        ).pack(side="left", padx=7)
        tk.Button(footer, text="关闭", command=self.close, relief="flat", bg=ROOM_BG).pack(
            side="right"
        )

    def _unlock(self) -> None:
        self.mind.set_room_locked(False)
        self._render()

    def _lock(self) -> None:
        self.mind.set_room_locked(True)
        self._render()


__all__ = ("PrivateRoomWindow",)
