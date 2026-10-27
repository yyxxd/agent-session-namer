# Agent Session Namer

为 Codex 和 Claude Code 自动整理对话标题。两个实现分别运行、分别配置；默认标题不超过 15 个 Unicode 字符，在 Git 附加工作树中的新标题以 🌳 开头。

| 版本 | 默认模型 | 触发时机 | 说明 |
| --- | --- | --- | --- |
| [Codex](codex/README.md) | GPT-6 Luna Fast | 每轮结束 | 通过 Codex 登录的账号调用独立命名会话 |
| [Claude Code](claude/README.md) | Claude Haiku 5.5 | 用户提交消息 | 通过已登录的 Claude Code CLI 调用独立命名会话 |

模型调用使用相应账号的可用额度，受订阅、模型权限和使用限制约束。标题由对话内容生成；如果现有标题被手动固定或识别为手动修改，自动命名会遵循各版本的保护规则。

## 来源与许可

Codex 版本基于 [oil-oil/oil-codex-title](https://github.com/oil-oil/oil-codex-title) 修改；Claude 版本受该项目启发，移植了部分命名规则和提示词。感谢原作者 oil。上游采用 MIT 许可，原版权声明和许可全文保留在 [LICENSE](LICENSE)。

这些实现不是原项目官方发布版本。当前仓库的桌面端自动触发仍需在各自环境中验证。
