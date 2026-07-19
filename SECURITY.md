# Security Policy

## Supported versions

LIFE-Mind 目前处于早期开发阶段，只为默认分支和最新发布版本提供安全修复。

## Reporting a vulnerability

安全问题可能涉及本地记忆、提示注入、路径处理、数据库删除或意外公开私人素材。请优先
使用 GitHub 仓库的 **Private vulnerability reporting**，不要在公开 Issue 中上传数据库、
日志、聊天记录、截图、API Key、Token、数据库备份、恢复副本或完整的
`%LOCALAPPDATA%\LIFE-Mind` 目录。需要说明本地数据健康状态时，只提交 `--doctor` 的脱敏输出。

报告中请只包含：

- 受影响版本或提交；
- 最小化且已经脱敏的复现步骤；
- 预期行为与实际行为；
- 影响范围；
- 可以安全公开的修复建议。

如果仓库尚未启用私密漏洞报告，请先创建不包含漏洞细节的普通 Issue，请维护者开启私密
沟通渠道。收到报告后，维护者会先确认影响范围，再决定修复与披露时间。

## Local data boundary

本项目默认将对话、记忆、关系、日记和本地 AI 设置保存在用户设备。请勿在安全报告、
测试夹具或 Pull Request 中提交真实用户数据。
