# 像素角色与动画素材指南

## 目标

动作库需要在透明桌面窗口中保持身份稳定、轮廓清楚和切换平滑。公开仓库只提供程序生成
的中立演示角色；使用者应在本地接入自己拥有再发布权或仅供私人使用的角色素材。

## 动作库结构

```text
my-character/
├─ manifest.json
├─ idle/frame_000.png
├─ blink/frame_000.png
├─ greet/frame_000.png
└─ ...
```

推荐提供以下 16 组动作：

```text
idle blink draw water work sleep greet happy
curious surprised pensive relieved look_around hum sit_down stand_up
```

每组可以使用不同帧数和速度，但同一动作内应保持固定画布、脚底基线与视觉锚点。

## 清单格式

```json
{
  "format": 2,
  "style": "refined-pixel-art",
  "identity": "my-character-v1",
  "display_name": "我的桌宠",
  "default_clip": "idle",
  "canvas": [420, 400],
  "clips": {
    "idle": {"duration_ms": 80, "loop": true, "frames": 12}
  }
}
```

- `identity` 必须非空且在同一角色的升级中保持稳定；
- `display_name` 只控制界面显示，可以改变；
- PNG 必须使用真实透明通道，不得以白色或棋盘格冒充透明；
- 播放器按 `frame_000.png`、`frame_001.png` 的顺序读取帧；
- `duration_ms` 是单帧时长，不是整组动画时长。

## 视觉稳定性

1. 所有帧使用相同画布尺寸；
2. 主体脚底或坐姿接触点固定，不在动作切换时横向漂移；
3. 人物边界不得因裁切框变化突然放大或缩小；
4. 手臂放下、坐下和站起必须包含完整收势帧；
5. 道具方向、作用位置和粒子方向保持一致；
6. 眨眼、头发和服饰摆动使用舒缓节奏，避免每帧大幅跳变；
7. 像素画缩放使用最近邻采样。

动画分析工具使用 `numpy`。首次运行前安装开发依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

然后检查动作库：

```powershell
python -B run_pet.py --asset D:\path\to\my-character --check
python -B tools/qa_animation_pack.py --root D:\path\to\my-character --strict
python -B tools/audit_animation_transitions.py --root D:\path\to\my-character --report qa-report.json --sheet qa-sheet.png
```

通用严格检查默认要求每组至少 12 帧，并允许动作本身造成有限的高度变化。高帧率角色可以
提高要求，例如：

```powershell
python -B tools/qa_animation_pack.py --root D:\path\to\my-character --strict --min-frames 48 --max-head-jitter 2 --max-baseline-jitter 0
```

## 切换原则

- 循环动作在收势点响应切换；
- 反应和坐立过渡只播放一次；
- 跨动作过程应保持单一人物轮廓；
- 状态机决定何时切换，渲染层不得随机触发动作；
- 素材插值只能补充时间采样，不能用重叠的两个人物伪造流畅。

## 私人素材

项目默认忽略 `assets/character/` 中除说明文件外的全部内容。不要使用 `git add -f`
绕过保护。角色原图、动作帧、模型、音乐和第三方来源包必须由使用者自行确认权利范围。
