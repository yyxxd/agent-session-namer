# Codex 版本

本目录是完整的 Codex 插件，基于 [oil-oil/oil-codex-title](https://github.com/oil-oil/oil-codex-title) 修改。它使用已登录的 Codex CLI 账户，默认 `gpt-6-luna` 的 Fast 档位。运行需要本地 Codex、Python 3.10+ 和 Git。

## 安装

将本仓库提供给 Codex，要求它从本仓库的 `codex/` 目录按官方插件安装流程安装完整插件，并在 Hook 管理入口启用和信任 Stop Hook。不要只复制 Skill。插件安装、Hook 信任和实际自动触发是不同状态。

在插件目录运行（Windows 使用 `py -3`，其他系统通常使用 `python3`）：

```powershell
py -3 -X utf8 skills/oil-codex-title/scripts/run.py doctor
py -3 -X utf8 skills/oil-codex-title/scripts/run.py status
```

`doctor` 不代表桌面自动触发已验证；请在新对话完成一轮后检查标题。Windows 的其他说明见 [安装与验证](docs/Windows安装与验证.md)。

## 配置

```powershell
py -3 -X utf8 skills/oil-codex-title/scripts/run.py configure --max-title-length 15
py -3 -X utf8 skills/oil-codex-title/scripts/run.py configure --model gpt-6-luna --service-tier fast
```

长度可设置为 8～48 个 Unicode 字符，包含 emoji、空格和分隔符；模型应选择当前 Codex 账户支持的模型。更换模型时 Fast 需要模型支持。只影响后续自动命名，不批量修改现有标题。

使用方法、标题保护和可选归档流程见 [Skill](skills/oil-codex-title/SKILL.md) 与 [归档工作流](docs/归档工作流.md)。
