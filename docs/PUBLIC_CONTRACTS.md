# LIFE-Mind 公开协议 0.1

三个公开协议把角色内容、外部能力和人生经验分开。JSON Schema 方便其他语言和编辑器接入；
`life_mind/contracts.py` 是 Python 参考宿主的语义校验实现。

0.1 版先稳定数据边界。当前 Pet Host 仍直接读取既有动画库，尚未提供完整 Life Package 的
安装/切换流程；Capability Manifest 也尚未连接第三方插件加载器。

## 快速验证

```powershell
python -B tools/validate_contract.py life-package examples/life-package.demo.json
python -B tools/validate_contract.py capability-manifest examples/capability-manifest.demo.json
python -B tools/validate_contract.py experience examples/experience.demo.json
```

结构定义和最小公开示例：

| 协议 | JSON Schema | 示例 |
|---|---|---|
| Life Package | [`life-package.schema.json`](../schemas/life-package.schema.json) | [`life-package.demo.json`](../examples/life-package.demo.json) |
| Capability Manifest | [`capability-manifest.schema.json`](../schemas/capability-manifest.schema.json) | [`capability-manifest.demo.json`](../examples/capability-manifest.demo.json) |
| Experience Protocol | [`experience-protocol.schema.json`](../schemas/experience-protocol.schema.json) | [`experience.demo.json`](../examples/experience.demo.json) |

JSON Schema 负责语言中立的结构验证；Python 校验器还执行跨字段规则，例如初始气质必须落在
声明范围内、网络能力必须提供纯域名白名单。这些规则必须同时通过才算参考实现兼容。

## Life Package

Life Package 描述角色的出生条件，而不是最终人生剧本：

- `identity`、`visuals`、`animations`、`voice`：身份和表现资源入口；
- `temperamentRanges`：可出生的气质范围；
- `initialValues`：本次实例在范围中的起点；
- `possibleConflicts`、`latentTraitPool`：可能浮现的矛盾和潜质，不是必然解锁表；
- `expressionStyle`：表达倾向和需要避免的模式；
- `growthConstraints`：成长证据和并行人物弧限制；
- `contentLicense`：代码与素材的权利和再分发边界。

角色包不能直接写入用户关系、历史记忆或已完成的成长结果。同一个 Life Package 在不同经历
下应允许产生不同的 Current Self，同时始终受 Core Self 和安全底线约束。

## Capability Manifest

能力权限使用 `类别:资源`：

- `observe:*`：可以看见某类事件；
- `memory:*`：可以请求写入某类记忆；
- `action:*`：可以请求执行某类动作；
- `share:*`：可以请求向指定边界之外传递数据；
- `network:*`、`device:*`、`ui:*`：网络、设备和界面能力。

四种权利不能合并推断：

```text
能够观察 ≠ 能够记忆 ≠ 能够使用 ≠ 能够分享
```

Manifest 只是请求清单。一次调用必须同时满足：能力已声明、用户显式授权、资源不在禁止项、
数据范围匹配、配额未耗尽和网络目标位于白名单。`credentials`、`private-messages` 与
`background-surveillance` 及其子范围在 0.1 参考实现中不可授权。

当前仓库只提供数据契约和单次授权判定原语，**不提供第三方代码沙箱**。在后续 Capability
Runtime 完成进程隔离、生命周期、配额计数、独立存储、SSRF 防护和审计前，不应加载不受
信任的插件。

## Experience Protocol

每次可进入心智的经历都要保留事实和解释的区别：

- `observation`：来源直接提供的观察，至少有一条可读摘要；
- `interpretation`：角色当前如何理解，可以保留备选解释；
- `uncertainty`：对整个经验解释的不确定程度；
- `emotionImpact`：候选情绪影响，不等于最终状态；
- `action`、`outcome`：做了什么和结果如何；
- `privacy.level`、`privacy.allowedUses`：敏感度与明确用途；
- `growthCandidates`：可进入证据审查的线索，不能直接推进成长阶段。

Python 参考实现可把它转换为既有 `MindEvent`。转换仍不会自动改变人格；事件要继续经过
社会评价、候选行为、安全仲裁、记忆治理和成长证据门槛。

## 版本兼容

- 0.1 校验器拒绝未知顶层字段和不支持的 `schemaVersion`，避免悄悄忽略安全语义。
- 扩展信息应放入协议允许的嵌套对象，或等待新协议版本，不要私自增加顶层字段。
- 发布角色或能力包时必须保留素材许可证、署名和兼容范围。
- 协议仍处于预览期；破坏性调整会提升协议版本并记录在 `CHANGELOG.md`。
