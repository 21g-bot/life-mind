"""Transparent Windows desktop pet with a state-driven pixel animation library."""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from life_mind.ai import (
    AIConfig,
    APISecretStore,
    LocalAIError,
    PROVIDER_PRESETS,
    credential_id,
    create_ai_client,
    endpoint_is_remote,
    endpoint_transport_allowed,
    provider_preset,
)
from life_mind.behavior import BehaviorDecision, BehaviorStateMachine
from life_mind.apps.private_room import PrivateRoomWindow
from life_mind.apps.system_tray import SystemTrayController
from life_mind.mind import MindEngine


CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LIFE-Mind"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Writable and optional character locations for source and frozen runs."""

    root: Path
    private_animation_dir: Path
    demo_animation_dir: Path


def resolve_runtime_paths(
    *,
    frozen: bool | None = None,
    module_file: Path | None = None,
    executable: Path | None = None,
    config_dir: Path | None = None,
) -> RuntimePaths:
    """Keep generated/user assets outside a frozen application's internals."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    user_config_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    if is_frozen:
        distribution_root = Path(executable or sys.executable).resolve().parent
        return RuntimePaths(
            root=distribution_root,
            private_animation_dir=distribution_root / "character",
            demo_animation_dir=user_config_dir / "demo-character",
        )

    source_root = Path(module_file or __file__).resolve().parents[2]
    return RuntimePaths(
        root=source_root,
        private_animation_dir=source_root / "assets" / "character" / "pixel_pet_v2",
        demo_animation_dir=source_root / ".cache" / "demo-character",
    )


RUNTIME_PATHS = resolve_runtime_paths()
PROJECT_ROOT = RUNTIME_PATHS.root
PRIVATE_ANIMATION_DIR = RUNTIME_PATHS.private_animation_dir
DEMO_ANIMATION_DIR = RUNTIME_PATHS.demo_animation_dir
REQUIRED_PIXEL_STYLE = "refined-pixel-art"


def default_animation_dir() -> Path:
    """Prefer an explicitly configured/private pack, otherwise use the public demo."""

    configured = os.environ.get("LIFE_MIND_ASSET", "").strip()
    if configured:
        return Path(configured).expanduser()
    if (PRIVATE_ANIMATION_DIR / "manifest.json").is_file():
        return PRIVATE_ANIMATION_DIR
    return DEMO_ANIMATION_DIR


DEFAULT_ANIMATION_DIR = default_animation_dir()
CONFIG_PATH = CONFIG_DIR / "desktop-pet.json"
ALLOWED_SCALES = (1, 2, 3)
DISPLAY_HEIGHTS = {1: 330, 2: 440, 3: 570}
TRANSPARENT_KEY = "#010203"
SEATED_ACTIVITY_CLIPS = frozenset({"draw", "work", "sleep"})
SOFT_TRANSITION_DURATION_MS = 42


@dataclass(slots=True)
class PetConfig:
    x: int | None = None
    y: int | None = None
    scale: int = 2
    topmost: bool = True
    swaying: bool = True
    do_not_disturb: bool = False

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "PetConfig":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        if not isinstance(payload, dict):
            return cls()
        scale = payload.get("scale", 2)
        if type(scale) is not int or scale not in ALLOWED_SCALES:
            scale = 2
        x, y = payload.get("x"), payload.get("y")
        return cls(
            x=x if type(x) is int else None,
            y=y if type(y) is int else None,
            scale=scale,
            topmost=_safe_config_bool(payload.get("topmost"), True),
            swaying=_safe_config_bool(payload.get("swaying"), True),
            do_not_disturb=_safe_config_bool(payload.get("do_not_disturb"), False),
        )

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def _safe_config_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


@dataclass(frozen=True, slots=True)
class GifAnimation:
    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]
    size: tuple[int, int]
    loop: bool = True

    @property
    def frame_count(self) -> int:
        return len(self.frames)


def _safe_duration(value: object, fallback: int) -> int:
    return max(20, int(value)) if isinstance(value, (int, float)) and value > 0 else fallback


def next_frame_cursor(animation: GifAnimation, cursor: int) -> int:
    """Advance once; one-shot clips hold their final pose instead of looping."""
    if animation.frame_count <= 1:
        return 0
    if cursor + 1 < animation.frame_count:
        return cursor + 1
    return 0 if animation.loop else animation.frame_count - 1


def make_soft_transition_frames(
    source: Image.Image,
    target: Image.Image,
) -> tuple[Image.Image, ...]:
    """Fade one complete sprite out, then the next in, without double exposure."""
    if source.size != target.size:
        raise ValueError("transition frames must share one canvas size")

    def faded(frame: Image.Image, opacity: float) -> Image.Image:
        output = frame.convert("RGBA").copy()
        output.putalpha(output.getchannel("A").point(lambda value: round(value * opacity)))
        return output

    # The two faint middle frames use different sprites. They never overlap,
    # so incompatible arms, props or body poses cannot create a ghost image.
    return tuple(
        faded(frame, opacity)
        for frame, opacity in (
            (source, 1.00),
            (source, 0.62),
            (source, 0.24),
            (target, 0.24),
            (target, 0.62),
            (target, 1.00),
        )
    )


def activity_transition_clips(current: str, target: str) -> tuple[str, ...]:
    """Return only physical posture changes; same-posture actions stay put."""
    currently_seated = current in SEATED_ACTIVITY_CLIPS
    target_seated = target in SEATED_ACTIVITY_CLIPS
    if currently_seated and not target_seated:
        return ("stand_up",)
    if not currently_seated and target_seated:
        return ("sit_down",)
    return ()


def resolved_clip_duration(animation: GifAnimation, requested_ms: int = 0) -> int:
    """Never let a sequence timer cut a clip before its final frame was held."""
    natural_duration = sum(animation.durations_ms)
    return max(natural_duration, requested_ms) if requested_ms > 0 else natural_duration


def autonomy_tick_allowed(
    *,
    do_not_disturb: bool,
    dragging: bool,
    paused: bool,
    reacting: bool,
    sequencing: bool,
    dialogue_in_progress: bool = False,
) -> bool:
    """Gate only unsolicited activity; user-initiated dialogue remains available."""

    return not any(
        (
            do_not_disturb,
            dragging,
            paused,
            reacting,
            sequencing,
            dialogue_in_progress,
        )
    )


def load_frame_sequence(path: Path, duration_ms: int = 250, *, loop: bool = True) -> GifAnimation:
    files = sorted(Path(path).glob("frame_*.png"))
    if not files:
        raise FileNotFoundError(f"找不到高清桌宠帧：{path}")
    frames: list[Image.Image] = []
    for file in files:
        with Image.open(file) as image:
            frames.append(image.convert("RGBA").copy())
    size = frames[0].size
    if any(frame.size != size for frame in frames):
        raise ValueError("高清桌宠帧尺寸不一致")
    return GifAnimation(tuple(frames), tuple([duration_ms] * len(frames)), size, loop)


def load_animation_library(
    path: Path,
    *,
    clip_names: set[str] | frozenset[str] | None = None,
) -> tuple[dict[str, GifAnimation], str]:
    """Load named pixel-animation clips described by a small JSON manifest."""

    path = Path(path)
    payload = load_animation_manifest(path)
    clips_payload = payload["clips"]
    default_name = str(payload["default_clip"])
    requested = set(clips_payload) if clip_names is None else set(clip_names) | {default_name}
    unknown = requested.difference(clips_payload)
    if unknown:
        raise ValueError(f"像素动作库缺少动作：{', '.join(sorted(unknown))}")

    clips: dict[str, GifAnimation] = {}
    expected_size: tuple[int, int] | None = None
    for name, options in clips_payload.items():
        if name not in requested:
            continue
        if not isinstance(name, str) or not isinstance(options, dict):
            continue
        duration = _safe_duration(options.get("duration_ms"), 300)
        clip = load_frame_sequence(
            path / name,
            duration_ms=duration,
            loop=bool(options.get("loop", True)),
        )
        if expected_size is None:
            expected_size = clip.size
        elif clip.size != expected_size:
            raise ValueError(f"动作 {name} 的帧尺寸与其他动作不一致")
        clips[name] = clip
    if not clips:
        raise ValueError("像素动作清单没有可用动作")
    return clips, default_name


def load_animation_manifest(path: Path) -> dict[str, object]:
    """Validate a pixel character library without hard-coding one private identity."""

    path = Path(path)
    if not path.is_dir():
        raise ValueError("桌宠运行时只接受像素动作库目录，不接受旧 GIF 或壁纸素材")
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到像素动作清单：{manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"像素动作清单无法读取：{manifest_path}") from error
    if payload.get("style") != REQUIRED_PIXEL_STYLE:
        raise ValueError(f"动作库必须声明像素风格：{REQUIRED_PIXEL_STYLE}")
    identity = payload.get("identity")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("动作库必须声明非空 identity")
    expected_identity = os.environ.get("LIFE_MIND_CHARACTER_IDENTITY", "").strip()
    if expected_identity and identity != expected_identity:
        raise ValueError(f"动作库 identity 与本机锁定角色不一致：{expected_identity}")
    clips_payload = payload.get("clips")
    if not isinstance(clips_payload, dict) or not clips_payload:
        raise ValueError("像素动作清单没有 clips")

    default_name = payload.get("default_clip", "idle")
    if not isinstance(default_name, str) or default_name not in clips_payload:
        raise ValueError("像素动作清单缺少有效的默认动作")
    return payload


def animation_report(path: Path) -> dict[str, object]:
    path = Path(path)
    manifest = load_animation_manifest(path)
    clips, default_name = load_animation_library(path)
    return {
        "path": str(path.resolve()),
        "type": "animation-library",
        "style": str(manifest["style"]),
        "identity": str(manifest["identity"]),
        "display_name": str(manifest.get("display_name", "")),
        "default_clip": default_name,
        "clips": len(clips),
        "clip_names": list(clips),
        "size": list(next(iter(clips.values())).size),
        "frames": sum(clip.frame_count for clip in clips.values()),
    }


def classify_user_text(text: str) -> tuple[str, str]:
    """Small deterministic reaction layer; the later mind engine can replace it."""
    normalized = text.strip().lower()
    if not normalized:
        return "…", "(｡•́︿•̀｡)"
    if any(word in normalized for word in ("不对", "错了", "不好", "不行", "讨厌")):
        return "…", "(´･ω･`)"
    if any(word in normalized for word in ("谢谢", "可爱", "喜欢", "厉害", "真棒", "好看", "乖")):
        return "♪", "(｡•̀ᴗ-)✧"
    if "?" in normalized or "？" in normalized or any(
        word in normalized for word in ("为什么", "怎么", "什么", "哪里", "谁", "吗", "呢")
    ):
        return "?", "(・_・?)"
    if "!" in normalized or "！" in normalized or any(
        word in normalized for word in ("真的", "居然", "竟然", "天啊", "震惊", "卧槽")
    ):
        return "!", "Σ(°△°|||)"
    return "♪", "( ´ ▽ ` )ﾉ"


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class NativeDesktopPet:
    def __init__(
        self,
        asset_path: Path = DEFAULT_ANIMATION_DIR,
        *,
        config_path: Path = CONFIG_PATH,
        mind_path: Path | None = None,
        windowed: bool = False,
        ui_qa_lightweight: bool = False,
        developer_mode: bool = False,
    ) -> None:
        self.asset_path = Path(asset_path)
        self.config_path = Path(config_path)
        self.developer_mode = bool(developer_mode)
        manifest = load_animation_manifest(self.asset_path)
        self.character_name = (
            os.environ.get("LIFE_MIND_NAME", "").strip()
            or str(manifest.get("display_name", "")).strip()
            or "桌宠"
        )
        self.available_clip_names = frozenset(str(name) for name in manifest["clips"])
        self.runtime_clip_names = (
            frozenset({"idle", "blink"}) if ui_qa_lightweight else self.available_clip_names
        )
        self.animations, self.current_clip_name = load_animation_library(
            self.asset_path,
            clip_names={str(manifest["default_clip"])},
        )
        self.animation = self.animations[self.current_clip_name]
        self.activity_clip_name = self.current_clip_name
        self.config = PetConfig.load(self.config_path)
        self.rng = random.Random()
        self.ai_secret_store = APISecretStore()
        self.ai_client = create_ai_client(AIConfig.load(), self.ai_secret_store)
        self.mind = (
            MindEngine(
                path=mind_path,
                ai_responder=self.ai_client,
                character_name=self.character_name,
            )
            if mind_path is not None
            else MindEngine(
                ai_responder=self.ai_client,
                character_name=self.character_name,
            )
        )
        self.behavior = BehaviorStateMachine()

        self.root = tk.Tk()
        self.root.title(f"LIFE-Mind · {self.character_name}")
        self.root.overrideredirect(not windowed)
        self.root.attributes("-topmost", self.config.topmost)
        self.root.configure(bg=TRANSPARENT_KEY)
        if self.mind.startup_recovery.status in {"restored", "reset"}:
            self.root.after(200, self._show_startup_recovery_notice)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.root,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.canvas.pack(fill="both", expand=True)
        self.character_item = self.canvas.create_image(0, 0, anchor="nw")
        self.bubble_items: list[int] = []

        self.frame_index = 0
        self.playback_order = self._playback_order()
        self.playback_cursor = 0
        self.paused = False
        self.dragging = False
        self.drag_offset = (0, 0)
        self.tk_frames: list[ImageTk.PhotoImage] = []
        self.tk_clips: dict[str, list[ImageTk.PhotoImage]] = {}
        self.blinking = False
        self.character_size = (1, 1)
        self.window_size = (1, 1)
        self.reaction_job: str | None = None
        self.clip_return_job: str | None = None
        self.frame_job: str | None = None
        self.sequence_job: str | None = None
        self.sequence_queue: list[tuple[str, int, bool]] = []
        self.sequence_final_clip = "idle"
        self.pending_activity_name: str | None = None
        self.hidden = False
        self.closing = False
        self.dialogue_in_progress = False
        self.dialogue_thread: threading.Thread | None = None
        self.tray: SystemTrayController | None = None
        self.private_room_window: PrivateRoomWindow | None = None

        self._build_menu()
        self._bind_events()
        # Map a real pixel frame before building the full 48-frame Tk cache.
        # This keeps cold start visibly responsive while preserving authored
        # animation frames once initialization finishes.
        self._rebuild_scaled_frames(first_frame_only=True)
        self._place_initially()
        self._show_frame(0)
        self.root.update()
        self._rebuild_scaled_frames()
        self._show_frame(0)
        self._start_system_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._schedule_next_frame()
        self.root.after(3000, self._behavior_tick)
        self.root.after(self.rng.randint(7500, 12000), self._blink)

    def _playback_order(self) -> list[int]:
        return list(range(self.animation.frame_count))

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=False)
        self.pause_menu_index = 0
        self.menu.add_command(label="暂停动画", command=self.toggle_pause)
        self.dnd_var = tk.BooleanVar(value=self.config.do_not_disturb)
        self.menu.add_checkbutton(
            label="专注 / 勿扰模式",
            variable=self.dnd_var,
            command=self._apply_dnd_menu,
        )
        self.menu.add_command(label="隐藏到系统托盘", command=self.hide_to_tray)
        self.menu.add_command(label="和她说句话…", command=self.open_chat)
        self.menu.add_command(label="管理关于我的本地记忆…", command=self.open_memory_manager)
        self.menu.add_command(label="备份本地数据", command=self.backup_local_data)
        self.menu.add_command(label="打开她的房间…", command=self.open_private_room)
        self.menu.add_command(label="AI 模型设置…", command=self.open_ai_settings)
        if self.developer_mode:
            self.menu.add_separator()
            self.menu.add_command(label="开发者：状态摘要", command=self.show_state)
            self.menu.add_command(label="开发者：心智调试器…", command=self.open_mind_debugger)

        reaction_menu = tk.Menu(self.menu, tearoff=False)
        for label, symbol, face in (
            ("震惊", "!", "Σ(°△°|||)"),
            ("疑惑", "?", "(・_・?)"),
            ("开心", "♪", "(｡•̀ᴗ-)✧"),
            ("沉思", "…", "(´･ω･`)"),
            ("困倦", "Zz", "(－ω－) zzZ"),
        ):
            reaction_menu.add_command(label=label, command=lambda s=symbol, f=face: self.react(s, f))
        self.menu.add_cascade(label="看看反应", menu=reaction_menu)

        if len(self.runtime_clip_names) > 1:
            activity_menu = tk.Menu(self.menu, tearoff=False)
            for label, clip in (
                ("安静待着", "idle"),
                ("画点什么", "draw"),
                ("给花浇水", "water"),
                ("专心工作", "work"),
                ("坐下休息", "sleep"),
                ("四处看看", "look_around"),
                ("轻轻哼唱", "hum"),
            ):
                if clip in self.runtime_clip_names:
                    activity_menu.add_command(
                        label=label, command=lambda selected=clip: self.set_activity(selected)
                    )
            self.menu.add_cascade(label="让她做点什么", menu=activity_menu)

        size_menu = tk.Menu(self.menu, tearoff=False)
        self.scale_var = tk.IntVar(value=self.config.scale)
        for scale, label in ((1, "小巧"), (2, "标准"), (3, "较大")):
            size_menu.add_radiobutton(
                label=f"{label}（高约 {DISPLAY_HEIGHTS[scale]} px）",
                value=scale,
                variable=self.scale_var,
                command=lambda selected=scale: self.set_scale(selected),
            )
        self.menu.add_cascade(label="显示大小", menu=size_menu)

        self.swaying_var = tk.BooleanVar(value=self.config.swaying)
        self.menu.add_checkbutton(label="自动播放待机动作", variable=self.swaying_var, command=self.toggle_swaying)
        self.topmost_var = tk.BooleanVar(value=self.config.topmost)
        self.menu.add_checkbutton(label="始终置顶", variable=self.topmost_var, command=self.toggle_topmost)
        self.menu.add_command(label="回到右下角", command=self.move_to_bottom_right)
        self.menu.add_separator()
        self.menu.add_command(label="退出桌宠", command=self.close)

    def _bind_events(self) -> None:
        for widget in (self.root, self.canvas):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._finish_drag)
            widget.bind("<Button-3>", self._show_menu)
            widget.bind("<Double-Button-1>", lambda _event: self.react("♪", "(｡•̀ᴗ-)✧"))
        self.root.bind("<Escape>", lambda _event: self.close())

    def _rebuild_scaled_frames(self, *, first_frame_only: bool = False) -> None:
        target_height = DISPLAY_HEIGHTS[self.config.scale]
        source_width, source_height = next(iter(self.animations.values())).size
        target_width = max(1, round(source_width * target_height / source_height))
        self.tk_clips = {
            name: [
                ImageTk.PhotoImage(
                    frame.resize((target_width, target_height), Image.Resampling.NEAREST),
                    master=self.root,
                )
                for frame in (animation.frames[:1] if first_frame_only else animation.frames)
            ]
            for name, animation in self.animations.items()
        }
        self.tk_frames = self.tk_clips[self.current_clip_name]
        self.character_size = (target_width, target_height)
        self.window_size = (target_width + 220, target_height + 125)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.geometry(f"{self.window_size[0]}x{self.window_size[1]}+{x}+{y}")
        self.canvas.configure(width=self.window_size[0], height=self.window_size[1])
        self.canvas.coords(self.character_item, 10, 115)

    def _ensure_clip_loaded(self, name: str | None) -> bool:
        if not name or name not in self.runtime_clip_names:
            return False
        if name in self.animations:
            return True
        loaded, _ = load_animation_library(self.asset_path, clip_names={name})
        self.animations[name] = loaded[name]
        if self.character_size != (1, 1):
            width, height = self.character_size
            self.tk_clips[name] = [
                ImageTk.PhotoImage(
                    frame.resize((width, height), Image.Resampling.NEAREST),
                    master=self.root,
                )
                for frame in self.animations[name].frames
            ]
        return True

    def _release_unused_clips(self, *keep: str) -> None:
        protected = {"idle", self.current_clip_name, self.activity_clip_name, *keep}
        for name in tuple(self.animations):
            if name in protected:
                continue
            self.tk_clips.pop(name, None)
            self.animations.pop(name, None)

    def _place_initially(self) -> None:
        self.root.update_idletasks()
        if self.config.x is None or self.config.y is None:
            self.move_to_bottom_right(save=False)
        else:
            self.root.geometry(f"+{self.config.x}+{self.config.y}")
            self._keep_on_screen()

    def _show_frame(self, index: int) -> None:
        image = self.tk_frames[index]
        self.canvas.itemconfigure(self.character_item, image=image)
        self.canvas.image = image

    def _cancel_frame_job(self) -> None:
        if self.frame_job:
            try:
                self.root.after_cancel(self.frame_job)
            except tk.TclError:
                pass
            self.frame_job = None

    def _schedule_next_frame(self) -> None:
        self._cancel_frame_job()
        duration = self.animation.durations_ms[self.frame_index]
        self.frame_job = self.root.after(duration, self._advance_frame)

    def _advance_frame(self) -> None:
        self.frame_job = None
        should_animate = self.config.swaying or self.current_clip_name != "idle"
        if not self.paused and should_animate:
            if not self.animation.loop and self.playback_cursor >= self.animation.frame_count - 1:
                return
            previous_cursor = self.playback_cursor
            self.playback_cursor = next_frame_cursor(self.animation, previous_cursor)
            wrapped = self.animation.loop and self.playback_cursor < previous_cursor
            if wrapped and self.pending_activity_name:
                pending = self.pending_activity_name
                self.pending_activity_name = None
                self._begin_activity_transition(pending)
                return
            self.frame_index = self.playback_order[self.playback_cursor]
            if not self.blinking:
                self._show_frame(self.frame_index)
        self._schedule_next_frame()

    def _set_clip(self, name: str, *, return_after_ms: int | None = None) -> None:
        if name != "__soft_transition__" and not self._ensure_clip_loaded(name):
            return
        if name not in self.animations:
            return
        if self.clip_return_job:
            try:
                self.root.after_cancel(self.clip_return_job)
            except tk.TclError:
                pass
            self.clip_return_job = None
        self._cancel_frame_job()
        self.current_clip_name = name
        self.animation = self.animations[name]
        self.tk_frames = self.tk_clips[name]
        self.frame_index = 0
        self.playback_order = self._playback_order()
        self.playback_cursor = 0
        if not self.blinking:
            self._show_frame(0)
        self._schedule_next_frame()
        if return_after_ms:
            self.clip_return_job = self.root.after(return_after_ms, self._restore_activity_clip)

    def _cancel_sequence(self) -> None:
        if self.sequence_job:
            try:
                self.root.after_cancel(self.sequence_job)
            except tk.TclError:
                pass
        self.sequence_job = None
        self.sequence_queue.clear()

    def _install_soft_transition(self, target_name: str) -> tuple[str, int]:
        """Create a temporary six-frame single-sprite bridge to target frame zero."""
        if not self._ensure_clip_loaded(target_name):
            target_name = "idle"
        transition_name = "__soft_transition__"
        source = self.animation.frames[self.frame_index]
        target = self.animations[target_name].frames[0]
        frames = make_soft_transition_frames(source, target)
        animation = GifAnimation(
            frames,
            tuple([SOFT_TRANSITION_DURATION_MS] * len(frames)),
            source.size,
            loop=False,
        )
        self.animations[transition_name] = animation
        target_width, target_height = self.character_size
        self.tk_clips[transition_name] = [
            ImageTk.PhotoImage(
                frame.resize((target_width, target_height), Image.Resampling.NEAREST),
                master=self.root,
            )
            for frame in frames
        ]
        return transition_name, sum(animation.durations_ms)

    def _play_sequence(self, clips: list[tuple[str, int]], final_clip: str) -> None:
        self._cancel_sequence()
        available_clips: list[tuple[str, int, bool]] = []
        for name, duration in clips:
            if self._ensure_clip_loaded(name):
                available_clips.append((name, duration, True))
        self.sequence_queue = available_clips
        self.sequence_final_clip = final_clip if self._ensure_clip_loaded(final_clip) else "idle"

        def finish_on_final_clip() -> None:
            self.sequence_job = None
            if self.current_clip_name == self.sequence_final_clip:
                self._release_unused_clips(self.sequence_final_clip)
                return
            transition_name, transition_duration = self._install_soft_transition(
                self.sequence_final_clip
            )
            self._set_clip(transition_name)

            def finish() -> None:
                self.sequence_job = None
                self._set_clip(self.sequence_final_clip)
                self._release_unused_clips(self.sequence_final_clip)

            self.sequence_job = self.root.after(transition_duration, finish)

        def advance() -> None:
            self.sequence_job = None
            if not self.sequence_queue:
                finish_on_final_clip()
                return
            name, duration, needs_bridge = self.sequence_queue.pop(0)
            if needs_bridge and self.current_clip_name != name:
                transition_name, transition_duration = self._install_soft_transition(name)
                self.sequence_queue.insert(0, (name, duration, False))
                self._set_clip(transition_name)
                self.sequence_job = self.root.after(transition_duration, advance)
                return
            self._set_clip(name)
            actual_duration = resolved_clip_duration(self.animations[name], duration)
            self.sequence_job = self.root.after(actual_duration, advance)

        advance()

    def _begin_activity_transition(self, name: str) -> None:
        if not self._ensure_clip_loaded(name):
            name = "idle"
        if (
            name == self.activity_clip_name
            and name == self.current_clip_name
            and not self.sequence_job
        ):
            return
        transitions = [
            (clip, 0)
            for clip in activity_transition_clips(self.activity_clip_name, name)
            if self._ensure_clip_loaded(clip)
        ]
        self.activity_clip_name = name
        self._play_sequence(transitions, name)

    def _transition_to_activity(self, name: str) -> None:
        if not self._ensure_clip_loaded(name):
            name = "idle"
        if (
            self.animation.loop
            and self.current_clip_name == self.activity_clip_name
            and self.playback_cursor != 0
        ):
            # Let a watering/drawing/sleeping loop reach its authored boundary
            # instead of cutting the body at an arbitrary intermediate pose.
            self.pending_activity_name = name
            return
        self.pending_activity_name = None
        self._begin_activity_transition(name)

    def _restore_activity_clip(self) -> None:
        self.clip_return_job = None
        self._set_clip(self.activity_clip_name)
        self._release_unused_clips(self.activity_clip_name)

    def set_activity(self, name: str) -> None:
        decision = self.behavior.set_manual_activity(name)
        self.mind.apply_activity_effect(decision.activity, decision.reason)
        mind_decision = self.mind.last_mind_decision()
        selected_clip = str(mind_decision.get("clip") or decision.clip)
        self.behavior.current_activity = selected_clip
        self.behavior.last_reason = str(mind_decision.get("explanation") or decision.reason)
        self._transition_to_activity(selected_clip)

    def react(
        self,
        symbol: str,
        kaomoji: str = "",
        message: str = "",
        duration_ms: int = 3600,
        clip_name: str | None = None,
        animate: bool = True,
    ) -> None:
        self._clear_reaction()
        self._cancel_sequence()
        reaction_clip = None
        if animate:
            reaction_clip = clip_name or {
                "?": "curious",
                "!": "surprised",
                "♪": "happy",
                "…": "pensive",
                "Zz": "sleep",
            }.get(symbol)
        if self._ensure_clip_loaded(reaction_clip):
            seated = SEATED_ACTIVITY_CLIPS
            if (
                self.activity_clip_name in seated
                and reaction_clip not in seated
                and self._ensure_clip_loaded("stand_up")
            ):
                sequence = [("stand_up", 0), (reaction_clip, duration_ms)]
                if self.activity_clip_name in seated and self._ensure_clip_loaded("sit_down"):
                    sequence.append(("sit_down", 0))
                self._play_sequence(
                    sequence, self.activity_clip_name
                )
            else:
                self._play_sequence(
                    [(reaction_clip, duration_ms)], self.activity_clip_name
                )
        char_width, _ = self.character_size
        symbol_x, symbol_y = min(self.window_size[0] - 42, char_width + 42), 125
        self.bubble_items.append(
            self.canvas.create_text(
                symbol_x,
                symbol_y,
                text=symbol,
                fill="#F4A300",
                font=("Microsoft YaHei UI", 28, "bold"),
                anchor="center",
            )
        )
        bubble_text = kaomoji if not message else f"{kaomoji}\n{message}"
        if bubble_text:
            x0, y0, x1, y1 = 20, 6, min(self.window_size[0] - 8, 340), 102
            self.bubble_items.append(
                self.canvas.create_rectangle(x0, y0, x1, y1, fill="#FFF5CF", outline="#D99B37", width=2)
            )
            self.bubble_items.append(
                self.canvas.create_text(
                    (x0 + x1) // 2,
                    (y0 + y1) // 2,
                    text=bubble_text,
                    fill="#4A3628",
                    font=("Microsoft YaHei UI", 10),
                    width=max(120, x1 - x0 - 18),
                    justify="center",
                )
            )
        self.reaction_job = self.root.after(duration_ms, self._clear_reaction)

    def _clear_reaction(self) -> None:
        if self.reaction_job:
            try:
                self.root.after_cancel(self.reaction_job)
            except tk.TclError:
                pass
            self.reaction_job = None
        for item in self.bubble_items:
            self.canvas.delete(item)
        self.bubble_items.clear()

    def _behavior_tick(self) -> None:
        if autonomy_tick_allowed(
            do_not_disturb=self.config.do_not_disturb,
            dragging=self.dragging,
            paused=self.paused,
            reacting=bool(self.reaction_job),
            sequencing=bool(self.sequence_job),
            dialogue_in_progress=self.dialogue_in_progress,
        ):
            decision = self.behavior.tick(self.mind.state())
            if decision:
                self.mind.apply_activity_effect(decision.activity, decision.reason)
                mind_decision = self.mind.last_mind_decision()
                selected_clip = str(mind_decision.get("clip") or decision.clip)
                self.behavior.current_activity = selected_clip
                self.behavior.last_reason = str(mind_decision.get("explanation") or decision.reason)
                self._transition_to_activity(selected_clip)
        self.root.after(3000, self._behavior_tick)

    def _blink(self) -> None:
        if self.blinking or self.dragging or self.paused:
            self.root.after(self.rng.randint(2500, 4500), self._blink)
            return
        if self.current_clip_name == "idle" and self._ensure_clip_loaded("blink"):
            blink_duration = sum(self.animations["blink"].durations_ms)
            self._set_clip("blink", return_after_ms=blink_duration)
            self.root.after(self.rng.randint(10000, 18000), self._blink)
            return
        self.root.after(self.rng.randint(2500, 4500), self._blink)

    def open_chat(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"和{self.character_name}说句话")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        tk.Label(dialog, text=f"你想对{self.character_name}说什么？", padx=14, pady=8).pack(anchor="w")
        entry = tk.Entry(dialog, width=38, font=("Microsoft YaHei UI", 11))
        entry.pack(padx=14, pady=(0, 8))

        status = tk.Label(dialog, text="", fg="#7A6248")
        status.pack(pady=(0, 5))
        submit_button: tk.Button

        def submit(_event: tk.Event | None = None) -> None:
            text = entry.get().strip()
            if not text:
                return
            if self.dialogue_in_progress:
                status.configure(text=f"{self.character_name}还在想上一句话，请稍等一下。")
                return
            self.dialogue_in_progress = True
            entry.configure(state="disabled")
            submit_button.configure(state="disabled")
            status.configure(text=f"{self.character_name}正在想…")

            def work() -> None:
                try:
                    response = self.mind.process_user_text(text)
                except Exception:
                    def recover() -> None:
                        self.dialogue_in_progress = False
                        self.dialogue_thread = None
                        if not dialog.winfo_exists():
                            return
                        entry.configure(state="normal")
                        submit_button.configure(state="normal")
                        status.configure(text="这次处理没有完成，请稍后再试。")
                        entry.focus_force()

                    try:
                        self.root.after(0, recover)
                    except tk.TclError:
                        pass
                    return

                def deliver() -> None:
                    self.dialogue_in_progress = False
                    self.dialogue_thread = None
                    if dialog.winfo_exists():
                        dialog.destroy()
                    cue, decision = self.behavior.on_dialogue(
                        text, response.symbol, self.mind.state()
                    )
                    persistent_clips = {"draw", "water", "work", "sleep", "look_around", "hum"}
                    if response.mind_clip in persistent_clips:
                        self.behavior.set_manual_activity(response.mind_clip)
                        self.behavior.last_reason = f"心智仲裁：{response.mind_action}"
                        self._transition_to_activity(response.mind_clip)
                    else:
                        self.activity_clip_name = "idle"
                    self.react(
                        cue.symbol,
                        response.face,
                        response.text,
                        duration_ms=max(3200, cue.duration_ms),
                        clip_name=response.mind_clip or decision.clip,
                        animate=response.mind_clip not in persistent_clips,
                    )

                try:
                    self.root.after(0, deliver)
                except tk.TclError:
                    pass

            worker = threading.Thread(
                target=work,
                name="life-mind-dialogue",
                daemon=True,
            )
            self.dialogue_thread = worker
            worker.start()

        submit_button = tk.Button(
            dialog, text=f"说给{self.character_name}听", command=submit, padx=14
        )
        submit_button.pack(pady=(0, 12))
        entry.bind("<Return>", submit)
        entry.bind("<Escape>", lambda _event: dialog.destroy())
        entry.focus_force()

    def open_private_room(self) -> None:
        if self.private_room_window and self.private_room_window.exists():
            self.private_room_window.focus()
            return

        def cleared() -> None:
            self.private_room_window = None

        self.private_room_window = PrivateRoomWindow(
            self.root,
            self.mind,
            character_name=self.character_name,
            on_close=cleared,
        )

    def _show_startup_recovery_notice(self) -> None:
        recovery = self.mind.startup_recovery
        messagebox.showwarning(
            "本地数据恢复",
            f"{recovery.notice}\n\n原文件没有被删除，已保留在隔离目录中。",
            parent=self.root,
        )

    def backup_local_data(self) -> None:
        try:
            backup = self.mind.backup_now()
        except (OSError, sqlite3.Error, RuntimeError) as error:
            messagebox.showerror(
                "备份失败",
                f"本地数据没有被改动。\n\n{type(error).__name__}: {error}",
                parent=self.root,
            )
            return
        messagebox.showinfo(
            "备份完成",
            f"已生成经过完整性检查的本地快照：\n{backup.name}\n\n系统会保留最近 7 份。",
            parent=self.root,
        )

    def _export_memories_from_dialog(self, parent: tk.Misc) -> None:
        selected = filedialog.asksaveasfilename(
            parent=parent,
            title=f"导出{self.character_name}记住的事情",
            defaultextension=".json",
            filetypes=(("JSON 文件", "*.json"),),
            initialfile="life-mind-memories.json",
        )
        if not selected:
            return
        destination = self.mind.export_memories(Path(selected))
        messagebox.showinfo("导出完成", f"已导出到：\n{destination}", parent=parent)

    def open_memory_manager(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"{self.character_name}记住的事情")
        dialog.attributes("-topmost", True)
        dialog.geometry("760x410")
        tk.Label(
            dialog,
            text=(
                "这里仅用于管理关于你的本地数据，不会显示她的内部想法、关系拆分或成长过程。"
                "删除会同步清理索引、原事件和单一来源派生摘要。"
            ),
            anchor="w",
            wraplength=720,
            padx=12,
            pady=8,
        ).pack(fill="x")
        listbox = tk.Listbox(dialog, font=("Microsoft YaHei UI", 10))
        listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        records = []

        def refresh() -> None:
            nonlocal records
            records = self.mind.memories()
            listbox.delete(0, tk.END)
            for record in records:
                review = "待复核 · " if record.review_required else ""
                listbox.insert(
                    tk.END,
                    f"#{record.id}  {review}[{record.category}/{record.source}/{record.privacy.value}]  "
                    f"{record.content}",
                )

        def selected_record():
            selection = listbox.curselection()
            return records[selection[0]] if selection else None

        def correct() -> None:
            record = selected_record()
            if not record:
                return
            value = simpledialog.askstring(
                "纠正记忆",
                "请修改这条记忆：",
                initialvalue=record.content,
                parent=dialog,
            )
            if value is not None:
                try:
                    self.mind.update_memory(record.id, value)
                except ValueError as error:
                    messagebox.showerror("无法修改", str(error), parent=dialog)
                refresh()

        def confirm() -> None:
            record = selected_record()
            if not record or not record.review_required:
                return
            self.mind.confirm_memory(record.id)
            refresh()

        def delete() -> None:
            record = selected_record()
            if not record:
                return
            if messagebox.askyesno("删除记忆", f"确定删除这条记忆吗？\n\n{record.content}", parent=dialog):
                result = self.mind.delete_memory(record.id)
                refresh()
                messagebox.showinfo(
                    "已完成级联清理",
                    f"已删除 {len(result.deleted_ids)} 条记忆；"
                    f"{len(result.downgraded_ids)} 条多来源记忆已标记待复核。",
                    parent=dialog,
                )

        buttons = tk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(buttons, text="纠正选中记忆", command=correct).pack(side="left")
        tk.Button(buttons, text="删除选中记忆", command=delete).pack(side="left", padx=8)
        tk.Button(buttons, text="确认待复核记忆", command=confirm).pack(side="left")
        tk.Button(
            buttons,
            text="导出 JSON",
            command=lambda: self._export_memories_from_dialog(dialog),
        ).pack(side="left", padx=8)
        tk.Button(buttons, text="关闭", command=dialog.destroy).pack(side="right")
        refresh()

    def open_mind_debugger(self) -> None:
        if not self.developer_mode:
            raise PermissionError("心智调试器只在显式开发模式中开放")
        dialog = tk.Toplevel(self.root)
        dialog.title(f"{self.character_name}的心智调试器")
        dialog.attributes("-topmost", True)
        dialog.geometry("920x620+60+20")
        dialog.minsize(760, 520)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)

        header = tk.Frame(dialog)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        tk.Label(
            header,
            text="实时查看统一心智状态、三人关系、候选行为、安全拒绝与成长证据",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")

        notebook = ttk.Notebook(dialog)
        notebook.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 10))

        overview_tab = tk.Frame(notebook)
        relation_tab = tk.Frame(notebook)
        decision_tab = tk.Frame(notebook)
        growth_tab = tk.Frame(notebook)
        history_tab = tk.Frame(notebook)
        ai_audit_tab = tk.Frame(notebook)
        notebook.add(overview_tab, text="状态总览")
        notebook.add(relation_tab, text="关系")
        notebook.add(decision_tab, text="最近仲裁")
        notebook.add(growth_tab, text="成长证据")
        notebook.add(history_tab, text="事件回放")
        notebook.add(ai_audit_tab, text="LLM 审计")

        overview = tk.Text(
            overview_tab, wrap="word", font=("Consolas", 10), height=14, padx=10, pady=10
        )
        overview.pack(fill="both", expand=True)

        relation_tree = ttk.Treeview(
            relation_tab,
            columns=("actor", "ability", "goodwill", "respect", "safety", "closeness", "repair"),
            show="headings",
            height=14,
        )
        relation_headings = {
            "actor": "人物",
            "ability": "能力信任",
            "goodwill": "善意信任",
            "respect": "尊重",
            "safety": "安全感",
            "closeness": "亲近",
            "repair": "修复信心",
        }
        for column, label in relation_headings.items():
            relation_tree.heading(column, text=label)
            relation_tree.column(column, width=80 if column == "actor" else 105, anchor="center")
        relation_tree.pack(fill="both", expand=True, padx=8, pady=8)

        decision = tk.Text(
            decision_tab, wrap="word", font=("Consolas", 9), height=14, padx=10, pady=10
        )
        decision.pack(fill="both", expand=True)
        growth = tk.Text(
            growth_tab, wrap="word", font=("Consolas", 10), height=14, padx=10, pady=10
        )
        growth.pack(fill="both", expand=True)
        history = tk.Listbox(history_tab, font=("Consolas", 9), height=14)
        history.pack(fill="both", expand=True, padx=8, pady=8)
        ai_audit = tk.Text(
            ai_audit_tab, wrap="word", font=("Consolas", 9), height=14, padx=10, pady=10
        )
        ai_audit.pack(fill="both", expand=True)

        # Keep the injection controls above the resizable notebook.  A bottom
        # toolbar can be pushed below the working area on high-DPI/small-height
        # displays even when the toplevel itself is visible.
        footer = tk.Frame(dialog)
        footer.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 2))
        footer.grid_columnconfigure(3, weight=1)
        tk.Label(footer, text="测试事件：").grid(row=0, column=0, sticky="w")
        injection_var = tk.StringVar(value="任务请求")
        injections = {
            "任务请求": ("task_request", "user", {"pressure": 0.75, "work_cost": 0.12}),
            "任务失败": ("task_failure", "user", {}),
            "尖锐批评": (
                "unfair_criticism",
                "critic",
                {
                    "content_validity": 0.65,
                    "delivery_acceptability": 0.04,
                    "benign_intent_probability": 0.18,
                },
            ),
            "友善指导": (
                "guidance",
                "guide",
                {
                    "content_validity": 0.92,
                    "delivery_acceptability": 0.94,
                    "benign_intent_probability": 0.92,
                },
            ),
            "自主画画": (
                "autonomous_activity",
                "companion",
                {"focus_activity": "draw", "context": "debug_private_time", "cost": 0.05},
            ),
            "修复：只有道歉": ("repair", "critic", {"step": "apology"}),
            "修复：承认伤害": ("repair", "critic", {"step": "acknowledgment"}),
            "修复：承担责任": ("repair", "critic", {"step": "responsibility"}),
            "修复：提供补救": ("repair", "critic", {"step": "remedy"}),
            "修复：行为改变": ("repair", "critic", {"step": "changed_behavior"}),
            "修复：时间验证": ("repair", "critic", {"step": "time_evidence"}),
        }
        injection_box = tk.Menubutton(
            footer,
            textvariable=injection_var,
            width=18,
            anchor="w",
            relief="raised",
            borderwidth=1,
            padx=6,
            pady=3,
            cursor="hand2",
        )
        injection_menu = tk.Menu(injection_box, tearoff=False)
        for injection_name in injections:
            injection_menu.add_radiobutton(
                label=injection_name,
                value=injection_name,
                variable=injection_var,
            )
        injection_box.configure(menu=injection_menu)
        injection_box.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=2)

        stage_names = {
            1: "依赖工作价值",
            2: "矛盾积累",
            3: "失败与危机",
            4: "形成独立价值",
        }

        def replace_text(widget: tk.Text, content: str) -> None:
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert("1.0", content)
            widget.configure(state="disabled")

        def refresh() -> None:
            snapshot = self.mind.debug_snapshot(40)
            state = snapshot["state"]
            body = state["body"]
            needs = state["needs"]
            attention = state["attention"]
            affect = state["affect"]
            stable = state["personality"]
            replace_text(
                overview,
                "\n".join(
                    (
                        f"心智 seed：{snapshot['seed']}",
                        f"已持久化事件：{snapshot['event_count']}",
                        f"当前 tick：{state['tick']}",
                        "",
                        "[身体]",
                        f"energy={body['energy']:.3f}  fatigue={body['fatigue']:.3f}  stress={body['stress']:.3f}  comfort={body['comfort']:.3f}",
                        "",
                        "[需要强度]",
                        f"rest={needs['rest']:.3f}  connection={needs['connection']:.3f}  autonomy={needs['autonomy']:.3f}",
                        f"competence={needs['competence']:.3f}  play={needs['play']:.3f}",
                        "",
                        "[注意与情绪]",
                        f"focus={attention['focus_target']}  budget={attention['attention_budget']:.3f}",
                        f"emotion={affect['dominant_emotion']}  valence={affect['valence']:.3f}  arousal={affect['arousal']:.3f}",
                        f"cause={affect['cause']}",
                        "",
                        "[稳定人格，只能由长期证据门槛改变]",
                        "  ".join(f"{key}={value:.2f}" for key, value in stable.items()),
                        "",
                        f"回放异常：{snapshot['replay_errors'] or '无'}",
                    )
                ),
            )

            for item in relation_tree.get_children():
                relation_tree.delete(item)
            for actor_id, relation in state["relations"].items():
                relation_tree.insert(
                    "",
                    tk.END,
                    values=(
                        actor_id,
                        f"{relation['trust_ability']:.2f}",
                        f"{relation['trust_goodwill']:.2f}",
                        f"{relation['respect']:.2f}",
                        f"{relation['safety']:.2f}",
                        f"{relation['closeness']:.2f}",
                        f"{relation['repair_confidence']:.2f}",
                    ),
                )

            trace = snapshot["last_trace"]
            if trace:
                appraisal = trace["social_appraisal"]
                selected = trace["selected_action"]
                lines = [
                    f"事件：{trace['event']['event_type']}  {trace['event']['event_id']}",
                    f"来源：{trace['event']['source']} / actor={trace['event']['actor_id']}",
                    f"内容：{trace['event']['content']}",
                    "",
                    "[社会评价]",
                    f"内容可信={appraisal['content_validity']:.3f}  表达可接受={appraisal['delivery_acceptability']:.3f}  善意概率={appraisal['benign_intent_probability']:.3f}",
                    f"解释：{appraisal['explanation']}",
                    "",
                    f"[选中] {selected['action']}  score={selected['score']:.4f}",
                    f"原因：{selected['explanation']}",
                    "",
                    "[全部候选]",
                ]
                for candidate in trace["candidates"]:
                    mark = "✓" if candidate["allowed"] else "×"
                    suffix = f"；拒绝：{candidate['rejection']}" if candidate["rejection"] else ""
                    lines.append(
                        f"{mark} {candidate['action']}  score={candidate['score']:.4f}  {candidate['explanation']}{suffix}"
                    )
                if trace["notes"]:
                    lines.extend(("", "[证据记录]", *trace["notes"]))
                replace_text(decision, "\n".join(lines))
            else:
                replace_text(decision, "还没有统一心智事件。")

            growth_state = state["growth"]
            visible_growth = dict(snapshot.get("visible_growth", {}))
            visible_signals = [dict(item) for item in visible_growth.get("signals", ())]
            visible_artifacts = [dict(item) for item in visible_growth.get("artifacts", ())]
            stage = int(growth_state["stage"])
            replace_text(
                growth,
                "\n".join(
                    (
                        f"当前阶段：{stage} / 4 — {stage_names.get(stage, '未知')}",
                        f"叙事章节：{growth_state['narrative_chapter']}",
                        f"核心矛盾：{growth_state['active_conflict']}",
                        "",
                        f"旧模式觉察：{growth_state['awareness_count']}",
                        f"疲劳中继续工作：{growth_state['overwork_choices']}（阶段 2 要求 ≥2）",
                        f"疲劳失败：{growth_state['failure_under_fatigue']}（阶段 3 要求 ≥1）",
                        f"独立选择：{growth_state['independent_choices']}（阶段 4 要求 ≥3）",
                        f"不同情境：{len(growth_state['independent_contexts'])}（要求 ≥2）",
                        f"承担代价：{growth_state['cost_paid']:.3f}（要求 ≥0.15）",
                        f"证据一致反思：{growth_state['aligned_reflections']}（要求 ≥1）",
                        "",
                        "独立选择情境：",
                        *(f"- {item}" for item in growth_state["independent_contexts"]),
                        "",
                        "用户可观察信号：",
                        *(
                            f"- {item['title']}｜证据 {', '.join(item['evidence_event_ids'])}"
                            for item in visible_signals
                        ),
                        "",
                        "已解锁纪念物：",
                        *(
                            f"- {item['symbol']} {item['title']}｜证据 {', '.join(item['evidence_event_ids'])}"
                            for item in visible_artifacts
                        ),
                    )
                ),
            )

            history.delete(0, tk.END)
            for item in snapshot["recent_traces"]:
                event = item["event"]
                selected = item["selected_action"]
                change = f"  [{item['growth_change']}]" if item["growth_change"] else ""
                history.insert(
                    tk.END,
                    f"{event['event_id']} | {event['event_type']} -> {selected['action']}{change}",
                )
            replace_text(
                ai_audit,
                json.dumps(
                    snapshot.get("last_ai_audit") or {"status": "还没有 AI 模型审计记录"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        def inject() -> None:
            label = injection_var.get()
            event_type, actor_id, metadata = injections[label]
            if not messagebox.askyesno(
                "注入测试事件",
                f"“{label}”会写入当前角色的真实事件历史，并影响关系和成长。\n\n确定继续吗？",
                parent=dialog,
            ):
                return
            self.mind.inject_debug_event(
                event_type,
                actor_id=actor_id,
                content=f"心智调试器注入：{label}",
                metadata=dict(metadata),
            )
            mind_decision = self.mind.last_mind_decision()
            clip = str(mind_decision.get("clip", ""))
            if self._ensure_clip_loaded(clip):
                if clip in {"draw", "water", "work", "sleep", "look_around", "hum"}:
                    self._transition_to_activity(clip)
                else:
                    self.react("…", "(・_・?)", f"测试事件：{label}", clip_name=clip)
            refresh()

        def action_label(parent: tk.Widget, text: str, command) -> tk.Label:
            widget = tk.Label(
                parent,
                text=text,
                relief="raised",
                borderwidth=1,
                padx=10,
                pady=3,
                cursor="hand2",
                bg="#F4EEE4",
                activebackground="#E6D8C5",
            )
            widget.bind("<Button-1>", lambda _event: command())
            return widget

        action_label(footer, "注入并观察", inject).grid(row=0, column=2, sticky="w")
        action_label(footer, "刷新", refresh).grid(
            row=0, column=4, sticky="e", padx=(8, 0)
        )
        action_label(footer, "关闭", dialog.destroy).grid(
            row=0, column=5, sticky="e", padx=(8, 0)
        )
        refresh()
        dialog.update_idletasks()

    def open_ai_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"{self.character_name}的 AI 模型")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        config = self.ai_client.config
        presets_by_label = {preset.label: preset for preset in PROVIDER_PRESETS}
        selected_preset = provider_preset(config.provider)
        enabled_var = tk.BooleanVar(value=config.enabled)
        provider_var = tk.StringVar(value=selected_preset.label)
        endpoint_var = tk.StringVar(value=config.endpoint)
        model_var = tk.StringVar(value=config.model)
        api_key_var = tk.StringVar()
        share_memory_var = tk.BooleanVar(value=config.share_memory)
        tk.Checkbutton(dialog, text="启用 AI 对话增强", variable=enabled_var).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 7)
        )
        tk.Label(dialog, text="模型服务").grid(row=1, column=0, sticky="e", padx=(14, 7), pady=5)
        provider_box = ttk.Combobox(
            dialog,
            textvariable=provider_var,
            values=[preset.label for preset in PROVIDER_PRESETS],
            width=42,
            state="readonly",
        )
        provider_box.grid(row=1, column=1, padx=(0, 14), pady=5)
        tk.Label(dialog, text="模型名称").grid(row=2, column=0, sticky="e", padx=(14, 7), pady=5)
        tk.Entry(dialog, textvariable=model_var, width=45).grid(row=2, column=1, padx=(0, 14), pady=5)
        tk.Label(dialog, text="API 密钥").grid(row=3, column=0, sticky="e", padx=(14, 7), pady=5)
        tk.Entry(dialog, textvariable=api_key_var, width=45, show="●").grid(
            row=3, column=1, padx=(0, 14), pady=5
        )
        key_hint = tk.Label(
            dialog, text="", fg="#6B5A45", justify="left", anchor="w", wraplength=360
        )
        key_hint.grid(row=4, column=1, sticky="w", padx=(0, 14), pady=(0, 4))
        tk.Label(dialog, text="接口地址").grid(row=5, column=0, sticky="e", padx=(14, 7), pady=5)
        endpoint_entry = tk.Entry(dialog, textvariable=endpoint_var, width=45)
        endpoint_entry.grid(row=5, column=1, padx=(0, 14), pady=5)
        tk.Checkbutton(
            dialog,
            text="允许把已获准使用的长期记忆发给当前模型",
            variable=share_memory_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 2))
        privacy = tk.Label(dialog, text="", fg="#8A633C", justify="left", wraplength=470)
        privacy.grid(row=7, column=0, columnspan=2, padx=14, pady=(2, 5))
        status = tk.Label(
            dialog,
            text="密钥只保存在系统凭据库，也可以使用厂商环境变量。",
            fg="#6B5A45",
            justify="left",
            wraplength=470,
        )
        status.grid(row=8, column=0, columnspan=2, padx=14, pady=6)

        current_provider_id = [config.provider]

        def update_key_hint() -> None:
            preset = presets_by_label[provider_var.get()]
            environment = preset.api_key_env or "无需密钥"
            try:
                stored = bool(
                    self.ai_secret_store.get(
                        credential_id(preset.provider_id, endpoint_var.get())
                    )
                )
            except LocalAIError:
                stored = False
            credential_hint = (
                "系统凭据库已有密钥；留空可继续使用。"
                if stored
                else f"环境变量：{environment}"
            )
            key_hint.configure(
                text=credential_hint + (f"\n{preset.note}" if preset.note else "")
            )

        def update_privacy(*_args: object) -> None:
            remote = endpoint_is_remote(endpoint_var.get())
            privacy.configure(
                text=(
                    "☁ 云端接口：会发送当前消息、最近对话和语气状态摘要；长期记忆由上方选项决定。"
                    if remote
                    else "⌂ 本机接口：对话不会离开这台电脑。"
                )
            )

        def update_provider_fields(_event: tk.Event | None = None) -> None:
            preset = presets_by_label[provider_var.get()]
            if _event is not None:
                endpoint_var.set(preset.endpoint)
                model_var.set(preset.default_model)
            else:
                if not endpoint_var.get().strip():
                    endpoint_var.set(preset.endpoint)
                if not model_var.get().strip():
                    model_var.set(preset.default_model)
            if preset.remote and preset.provider_id != current_provider_id[0]:
                share_memory_var.set(False)
            current_provider_id[0] = preset.provider_id
            update_key_hint()
            update_privacy()

        provider_box.bind("<<ComboboxSelected>>", update_provider_fields)
        endpoint_entry.bind("<FocusOut>", lambda _event: update_key_hint())
        endpoint_var.trace_add("write", update_privacy)
        update_provider_fields()

        def save_and_check() -> None:
            preset = presets_by_label[provider_var.get()]
            endpoint = endpoint_var.get().strip().rstrip("/") or preset.endpoint
            if not endpoint.startswith(("http://", "https://")):
                status.configure(text="⚠ 接口地址必须以 http:// 或 https:// 开头。")
                return
            if not endpoint_transport_allowed(endpoint):
                status.configure(
                    text="⚠ 云端或局域网模型必须使用 HTTPS；HTTP 只允许本机回环地址。"
                )
                return
            same_destination = config.provider == preset.provider_id and config.endpoint == endpoint
            remote = endpoint_is_remote(endpoint)
            remote_consent = bool(
                same_destination
                and config.remote_consent
                and config.consent_endpoint.rstrip("/") == endpoint
            )
            consent_endpoint = endpoint if remote_consent else ""
            if enabled_var.get() and remote and not remote_consent:
                remote_consent = messagebox.askyesno(
                    "允许连接云端模型？",
                    "云端模型会收到你当前发送的消息、最近对话和用于调节语气的简短内部状态摘要。\n"
                    "只有勾选长期记忆共享时，获准用于模型上下文的记忆才会一并发送。\n\n"
                    "是否允许 LIFE-Mind 向这个接口发送这些数据？",
                    parent=dialog,
                )
                if not remote_consent:
                    status.configure(text="未保存：你没有授权向该云端接口发送对话。")
                    return
                consent_endpoint = endpoint
            if not remote:
                remote_consent = False
                consent_endpoint = ""
            new_config = AIConfig(
                enabled=enabled_var.get(),
                endpoint=endpoint,
                model=model_var.get().strip(),
                timeout_seconds=config.timeout_seconds,
                provider=preset.provider_id,
                api_key_env=preset.api_key_env,
                remote_consent=remote_consent,
                share_memory=share_memory_var.get(),
                consent_endpoint=consent_endpoint,
            )
            try:
                if api_key_var.get().strip():
                    self.ai_secret_store.set(
                        credential_id(preset.provider_id, endpoint), api_key_var.get()
                    )
            except LocalAIError as error:
                status.configure(text=f"⚠ {error}")
                return
            try:
                new_config.save()
            except OSError:
                status.configure(text="⚠ AI 配置未能写入本地设置目录。")
                return
            self.ai_client = create_ai_client(new_config, self.ai_secret_store)
            self.mind.ai_responder = self.ai_client
            api_key_var.set("")
            status.configure(text="正在检测模型接口…")
            client = self.ai_client

            def work() -> None:
                try:
                    ok, detail = client.status()
                except Exception:
                    ok, detail = False, "检测过程发生未预期错误，请检查接口与依赖。"

                def deliver_status() -> None:
                    if dialog.winfo_exists():
                        status.configure(text=("✓ " if ok else "⚠ ") + detail)

                try:
                    self.root.after(0, deliver_status)
                except tk.TclError:
                    pass

            threading.Thread(target=work, daemon=True).start()

        def clear_key() -> None:
            preset = presets_by_label[provider_var.get()]
            try:
                self.ai_secret_store.delete(
                    credential_id(preset.provider_id, endpoint_var.get())
                )
            except LocalAIError as error:
                status.configure(text=f"⚠ {error}")
                return
            api_key_var.set("")
            status.configure(text="已清除系统凭据库中的密钥；环境变量若存在仍会优先生效。")
            update_provider_fields()

        tk.Button(dialog, text="保存并检测", command=save_and_check).grid(
            row=9, column=0, pady=(4, 14), padx=(14, 5), sticky="e"
        )
        tk.Button(dialog, text="清除当前密钥", command=clear_key).grid(
            row=9, column=1, pady=(4, 14), padx=(5, 14), sticky="w"
        )

    def show_state(self) -> None:
        if not self.developer_mode:
            raise PermissionError("内部状态摘要只在显式开发模式中开放")
        state = self.mind.state()
        ai_config = self.ai_client.config
        messagebox.showinfo(
            f"{self.character_name}现在的状态",
            "\n".join(
                (
                    f"精力：{state.energy:.0%}",
                    f"心情：{state.mood:.0%}",
                    f"信任：{state.trust:.0%}",
                    f"主导情绪：{state.dominant_emotion}",
                    f"情绪原因：{state.emotion_cause}",
                    f"当前活动：{self.behavior.current_activity}",
                    f"活动原因：{self.behavior.last_reason}",
                    f"累计互动：{state.interaction_count} 次",
                    f"专注 / 勿扰：{'已开启' if self.config.do_not_disturb else '未开启'}",
                    f"系统托盘：{'运行中' if self.tray and self.tray.running else '不可用'}",
                    f"AI 模型：{'已启用' if ai_config.enabled else '已关闭'}",
                    f"服务：{provider_preset(ai_config.provider).label}",
                    f"模型：{ai_config.model or '自动选择'}",
                    "\n这些状态保存在本地，重启后仍会延续。",
                )
            ),
            parent=self.root,
        )

    def _start_drag(self, event: tk.Event) -> None:
        self.dragging = True
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        self.root.geometry(f"+{event.x_root - self.drag_offset[0]}+{event.y_root - self.drag_offset[1]}")

    def _finish_drag(self, _event: tk.Event) -> None:
        self.dragging = False
        self._remember_position()
        self._save_config()

    def _show_menu(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.menu.entryconfigure(self.pause_menu_index, label="继续动画" if self.paused else "暂停动画")
        if self.tray:
            self.tray.update_menu()

    def _apply_dnd_menu(self) -> None:
        self.set_do_not_disturb(bool(self.dnd_var.get()))

    def toggle_do_not_disturb(self) -> None:
        self.set_do_not_disturb(not self.config.do_not_disturb)

    def set_do_not_disturb(self, enabled: bool) -> None:
        self.config.do_not_disturb = bool(enabled)
        self.dnd_var.set(self.config.do_not_disturb)
        if self.config.do_not_disturb:
            self._clear_reaction()
            self.behavior.current_activity = "idle"
            self.behavior.last_reason = "专注 / 勿扰模式开启，停止主动活动与气泡"
            self._transition_to_activity("idle")
        else:
            self.behavior.next_decision_at = min(
                self.behavior.next_decision_at,
                time.monotonic() + 8.0,
            )
            self.behavior.last_reason = "专注 / 勿扰模式关闭，恢复低频自主生活"
        self._save_config()
        if self.tray:
            self.tray.update_menu()

    def _start_system_tray(self) -> None:
        icon_source = self.animations[self.current_clip_name].frames[0]
        self.tray = SystemTrayController(
            self.root,
            icon_source,
            is_hidden=lambda: self.hidden,
            toggle_visibility=self.toggle_visibility,
            is_do_not_disturb=lambda: self.config.do_not_disturb,
            toggle_do_not_disturb=self.toggle_do_not_disturb,
            is_paused=lambda: self.paused,
            toggle_pause=self.toggle_pause,
            close_application=self.close,
            character_name=self.character_name,
        )
        self.tray.start()

    def hide_to_tray(self) -> None:
        if not self.tray or not self.tray.running:
            messagebox.showwarning(
                "系统托盘不可用",
                "系统托盘没有成功启动，因此不会隐藏桌宠，避免无法恢复。",
                parent=self.root,
            )
            return
        self._clear_reaction()
        self.root.withdraw()
        self.hidden = True
        self.tray.update_menu()

    def show_from_tray(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", self.config.topmost)
        self.root.lift()
        self.hidden = False
        if self.tray:
            self.tray.update_menu()

    def toggle_visibility(self) -> None:
        if self.hidden:
            self.show_from_tray()
        else:
            self.hide_to_tray()

    def toggle_swaying(self) -> None:
        self.config.swaying = bool(self.swaying_var.get())
        if not self.config.swaying:
            if self.current_clip_name == "idle":
                self.frame_index = 0
                self._show_frame(self.frame_index)
        self._save_config()

    def toggle_topmost(self) -> None:
        self.config.topmost = bool(self.topmost_var.get())
        self.root.attributes("-topmost", self.config.topmost)
        self._save_config()

    def set_scale(self, scale: int) -> None:
        if scale not in ALLOWED_SCALES or scale == self.config.scale:
            return
        self.config.scale = scale
        self._rebuild_scaled_frames()
        self._show_frame(self.frame_index)
        self._keep_on_screen()
        self._save_config()

    def _keep_on_screen(self) -> None:
        width, height = self.window_size
        x = min(max(self.root.winfo_x(), 0), max(0, self.root.winfo_screenwidth() - width))
        y = min(max(self.root.winfo_y(), 0), max(0, self.root.winfo_screenheight() - height))
        self.root.geometry(f"+{x}+{y}")
        self._remember_position()

    def move_to_bottom_right(self, *, save: bool = True) -> None:
        width, height = self.window_size
        x = max(0, self.root.winfo_screenwidth() - width - 24)
        y = max(0, self.root.winfo_screenheight() - height - 64)
        self.root.geometry(f"+{x}+{y}")
        self._remember_position()
        if save:
            self._save_config()

    def _remember_position(self) -> None:
        self.config.x, self.config.y = self.root.winfo_x(), self.root.winfo_y()

    def _save_config(self) -> None:
        try:
            self.config.save(self.config_path)
        except OSError:
            pass

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        dialogue_thread = self.dialogue_thread
        self._remember_position()
        self._save_config()
        if self.tray:
            self.tray.stop()
        if self.private_room_window and self.private_room_window.exists():
            self.private_room_window.close()
        if dialogue_thread is not None and dialogue_thread.is_alive():
            self.root.destroy()

            def close_after_dialogue() -> None:
                dialogue_thread.join()
                self.mind.close()

            threading.Thread(
                target=close_after_dialogue,
                name="life-mind-shutdown",
                daemon=False,
            ).start()
            return
        self.mind.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


GifDesktopPet = NativeDesktopPet


def run_desktop_pet(
    asset_path: Path = DEFAULT_ANIMATION_DIR,
    *,
    config_path: Path = CONFIG_PATH,
    mind_path: Path | None = None,
    windowed: bool = False,
    ui_qa_lightweight: bool = False,
    developer_mode: bool = False,
) -> None:
    enable_windows_dpi_awareness()
    path = Path(asset_path)
    NativeDesktopPet(
        path,
        config_path=config_path,
        mind_path=mind_path,
        windowed=windowed,
        ui_qa_lightweight=ui_qa_lightweight,
        developer_mode=developer_mode,
    ).run()


__all__ = (
    "ALLOWED_SCALES",
    "DEMO_ANIMATION_DIR",
    "DEFAULT_ANIMATION_DIR",
    "GifAnimation",
    "GifDesktopPet",
    "NativeDesktopPet",
    "PetConfig",
    "PRIVATE_ANIMATION_DIR",
    "RuntimePaths",
    "SEATED_ACTIVITY_CLIPS",
    "activity_transition_clips",
    "animation_report",
    "autonomy_tick_allowed",
    "classify_user_text",
    "default_animation_dir",
    "enable_windows_dpi_awareness",
    "load_frame_sequence",
    "load_animation_library",
    "load_animation_manifest",
    "make_soft_transition_frames",
    "next_frame_cursor",
    "resolved_clip_duration",
    "resolve_runtime_paths",
    "run_desktop_pet",
)
