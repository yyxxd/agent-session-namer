# Claude Code 版本

在 Claude Code 的 `UserPromptSubmit` Hook 运行，通过已登录的 Claude Code CLI 以 `claude-haiku-5-5` 生成标题。它受 [oil-oil/oil-codex-title](https://github.com/oil-oil/oil-codex-title) 启发，并移植了部分命名规则和提示词。

## 前提

- 安装 Python 3.10+、Git 和支持 `--safe-mode` 的 Claude Code CLI，并确认 `claude` 可在命令行运行。
- 使用 Claude Code 登录具有模型使用权限的订阅账号。独立命名调用占用该账号额度，订阅及模型的可用性因账号而异。
- 需要本地 Claude Code 环境；桌面客户端对 Hook 标题的显示和刷新取决于版本及现有标题来源，需要实际验证。

## 安装

将 `namer.py` 和 `naming-prompt.md` 复制到 `~/.claude/session-namer/`，然后把以下 Hook 合并到 `~/.claude/settings.json` 的已有 `hooks` 中，保留已有设置及其他 Hook。`command` 必须替换成适用于本机的绝对路径：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "python3 /绝对路径/.claude/session-namer/namer.py", "timeout": 60}]}
    ]
  }
}
```

Windows 可使用 `py -3 -X utf8` 和加引号的绝对路径，注意 JSON 中反斜杠需要写成 `\\`。检查 Claude Code 的 Hook 管理界面并在新对话中验证。Hook 不支持或模型登录不可用时保留原标题，不阻塞对话。

## 配置

可在 `~/.claude/session-namer/config.json` 中设置：

```json
{"model": "claude-haiku-5-5", "max_title_length": 15, "min_turns": 2}
```

长度范围 8～48，包含 emoji、空格和分隔符。模型可以换成当前订阅支持的 Claude Code 模型 ID 或别名；不要求在此文件中保存 API Key。配置只影响后续自动命名，不批量修改已有标题。

命名会向独立模型会话发送最近几轮用户及助手的文本和当前标题；临时会话使用 `--safe-mode` 禁用自定义 Hook、`--tools ""` 禁用工具、`--strict-mcp-config` 排除 MCP，并使用 `--no-session-persistence`。发生失败时记录本地日志，当前标题不变。桌面端和 CLI 的登录状态可能不同，请先确认 CLI 已登录。
