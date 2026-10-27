#!/usr/bin/env python3
"""Claude Code 会话标题命名器。

在 UserPromptSubmit hook 中运行：读取最近对话，判断是否需要改名，
需要时调用独立模型生成候选标题，再通过 hookSpecificOutput.sessionTitle
交回 Claude Code 官方通道完成改名。

设计要点：
- 不直接写 transcript/sidecar/注册表，标题写入一律走官方 sessionTitle 字段。
- 用户手动改名后立即停止干预（检测到标题与上次记录不一致即锁定）。
- 任何失败都不阻塞会话，hook 始终返回可解析的 JSON。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    "enabled": True,
    "model": "claude-haiku-5-5",
    "recent_turns": 5,
    "model_timeout_seconds": 25,
    "min_turns": 2,
    "max_title_length": 15,
}
# 与 Codex 插件一致的类别表；正文只出现一个 emoji。
CATEGORIES = ("🎬", "🧩", "🔎", "📝", "📅", "🎨", "⚙️", "💬")
TITLE_PATTERN = re.compile(r"^(🎬|🧩|🔎|📝|📅|🎨|⚙️|💬) (.+?)｜(.+)$")


def data_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_NAMER_DATA")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "session-namer"


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default
    return value if isinstance(value, dict) else ({} if default is None else default)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_config() -> dict:
    config = DEFAULTS | read_json(data_dir() / "config.json")
    if not isinstance(config["enabled"], bool):
        raise ValueError("enabled 必须是布尔值")
    if not isinstance(config["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", config["model"]):
        raise ValueError("model 必须是有效的 Claude 模型 ID 或别名")
    for key, lower, upper in (("recent_turns", 3, 5),
                              ("model_timeout_seconds", 5, 60),
                              ("min_turns", 1, 10), ("max_title_length", 8, 48)):
        if type(config[key]) is not int or not lower <= config[key] <= upper:
            raise ValueError(f"{key} 必须在 {lower}～{upper} 之间")
    return config


def state_path(session_id: str) -> Path:
    return data_dir() / "state" / f"{session_id}.json"


def log(message: str) -> None:
    try:
        path = data_dir() / "logs" / f"{time.strftime('%Y-%m-%d')}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    except OSError:
        pass


# ── 会话内容读取 ────────────────────────────────────────────────────────────

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def strip_injected(text: str) -> str:
    """剥掉 Claude Code 注入的标记块，保留其余真实文本。

    处理两类：<system-reminder>…</system-reminder> 整块丢弃；
    <cross-session-message …>…</cross-session-message> 保留正文、丢掉标签。
    """
    cleaned = re.sub(r"<system-reminder>.*?</system-reminder>", " ", text, flags=re.S)
    cleaned = re.sub(r"</?cross-session-message[^>]*>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


# 子会话启动简报是父会话元信息，不算用户需求。
LAUNCH_PREFIXES = (
    "Background (from the session that started this one)",
    "Shared notes folder for this group of sessions",
)


def is_real_user_text(text: str) -> bool:
    """过滤 Claude Code 注入的伪用户消息（斜杠命令包装、system-reminder 等）。"""
    stripped = strip_injected(text)
    if not stripped:
        return False
    if stripped.startswith(LAUNCH_PREFIXES):
        return False
    # 整条都是 <tag>...</tag> 包裹的注入内容时判为伪消息。
    if re.match(r"^<[a-z][a-z0-9-]*>", stripped) and stripped.endswith("</system-reminder>"):
        return False
    if re.match(r"^<[a-z][a-z0-9-]*>", stripped) and not re.search(r"</[a-z][a-z0-9-]*>$", stripped):
        return False
    return True


def read_turns(transcript_path: str, recent_turns: int):
    """返回 (用户消息列表, 助手消息列表, 当前标题)。

    标题以 transcript 末尾的 custom-title 帧为准；桌面应用在改名后会回写该帧。
    """
    users, assistants, title = [], [], None
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                kind = entry.get("type")
                if kind == "custom-title":
                    title = entry.get("customTitle") or title
                elif kind == "user":
                    text = strip_injected(extract_text(entry.get("message", {}).get("content")))
                    if text and is_real_user_text(text):
                        users.append(text)
                elif kind == "assistant":
                    text = extract_text(entry.get("message", {}).get("content"))
                    if text:
                        assistants.append(text)
    except OSError:
        return [], [], None
    return users[-recent_turns:], assistants[-recent_turns:], title


def read_current_title(transcript_path: str, session_id: str):
    """读取当前权威标题。

    优先取 transcript 末尾的 custom-title 帧；取不到时回退到侧车文件。
    桌面应用在改名后会把权威标题回写到帧里，因此帧是可信来源。
    """
    _, _, title = read_turns(transcript_path, 1)
    if title:
        return title
    sidecar = Path(transcript_path).parent / session_id / "custom-title.json"
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("customTitle")
    return value if isinstance(value, str) and value else None


def fingerprint(turns) -> str:
    import hashlib
    payload = json.dumps(turns, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ── 模型调用 ────────────────────────────────────────────────────────────────

def build_prompt(users, assistants, current_title, project_hint, max_title_length) -> str:
    prompt_text = (ROOT / "naming-prompt.md").read_text(encoding="utf-8")
    payload = {
        "recent_user_messages": users,
        "recent_assistant_messages": assistants,
        "current_title": current_title,
        "project_hint": project_hint,
        "max_title_length": max_title_length,
    }
    return f"{prompt_text}\n\n输入 JSON：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def call_model(prompt: str, config: dict):
    """使用已登录的 Claude Code 订阅运行无工具临时会话。"""
    binary = shutil.which("claude")
    if not binary:
        raise RuntimeError("未找到 Claude Code CLI，请先安装并登录")
    cmd = [binary, "--print", "--safe-mode", "--tools", "", "--strict-mcp-config",
           "--no-session-persistence", "--model", config["model"], "--output-format", "json"]
    env = os.environ.copy()
    for key in ("CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        env.pop(key, None)
    try:
        with tempfile.TemporaryDirectory(prefix="session-namer-") as cwd:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, encoding="utf-8", cwd=cwd,
                                  env=env, timeout=config["model_timeout_seconds"],
                                  **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"模型调用失败：{exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError("Claude Code 模型调用失败，请检查登录和模型权限")
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError("模型返回不是合法 JSON") from exc
    if data.get("is_error"):
        raise RuntimeError("Claude Code 返回错误，请检查登录和模型权限")
    text = data.get("result", "")
    usage = data.get("usage", {}) or {}
    return parse_candidate(text), {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


def parse_candidate(text: str) -> dict:
    """从模型输出里取出 action/title/reason。"""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise RuntimeError("模型输出中没有 JSON")
    data = json.loads(match.group(0))
    if data.get("action") not in ("keep", "rename"):
        raise RuntimeError("action 必须是 keep 或 rename")
    title = str(data.get("title", "")).strip()
    reason = str(data.get("reason", "")).strip()[:60]
    return {"action": data["action"], "title": title, "reason": reason}


def is_linked_worktree(cwd: str) -> bool:
    if not cwd or not Path(cwd).is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
            capture_output=True, encoding="utf-8", timeout=5,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法判断对话是否位于工作树") from exc
    if result.returncode:
        return False
    paths = result.stdout.splitlines()
    if len(paths) != 2:
        raise RuntimeError("Git 返回了无效的工作树信息")
    return Path(paths[0]).resolve() != Path(paths[1]).resolve()


def validate_candidate(candidate: dict, current_title: str, max_length: int, worktree: bool) -> dict:
    """校验标题格式；不合法时降级为 keep。"""
    if candidate["action"] != "rename":
        return candidate
    title = candidate["title"]
    match = TITLE_PATTERN.match(title)
    if not match:
        return {"action": "keep", "title": current_title, "reason": "候选格式不合规，保留原名"}
    emoji, obj, goal = match.group(1), match.group(2).strip(), match.group(3).strip()
    if worktree:
        title = "🌳 " + title.split(" ", 1)[1]
    if not obj or not goal or len(title) > max_length:
        return {"action": "keep", "title": current_title, "reason": "候选格式不合规，保留原名"}
    if emoji not in CATEGORIES:
        return {"action": "keep", "title": current_title, "reason": "类别 emoji 不在允许列表，保留原名"}
    if title == current_title:
        return {"action": "keep", "title": current_title, "reason": "候选与当前标题相同"}
    return {"action": "rename", "title": title, "reason": candidate["reason"]}


# ── 主流程 ──────────────────────────────────────────────────────────────────

def process(session_id: str, transcript_path: str, cwd: str, prompt: str = "") -> dict:
    config = load_config()
    path = state_path(session_id)
    state = read_json(path)

    users, assistants, _ = read_turns(transcript_path, config["recent_turns"])
    # hook 触发时当前这条消息还没写进 transcript，直接用 stdin 里的 prompt 补上，
    # 否则永远少一轮，min_turns 判定会偏后一轮。
    current_prompt = strip_injected(prompt)
    if current_prompt and is_real_user_text(current_prompt) and (not users or users[-1] != current_prompt):
        users = (users + [current_prompt])[-config["recent_turns"]:]
    current_title = read_current_title(transcript_path, session_id)
    if len(users) < config["min_turns"]:
        log(f"skip: {session_id} (仅 {len(users)} 轮用户消息，未达 {config['min_turns']} 轮)")
        return {"status": "too_few_turns"}

    # 用户手动改名（/rename）后立即锁定，不再干预。
    # 判定依据：当前标题既不是上次观察到的标题，也不是本插件上次写出的标题。
    observed = state.get("last_observed_title")
    generated = state.get("last_generated_title")
    if (observed and current_title
            and current_title != observed
            and current_title != generated):
        state.update(locked=True, lock_reason="检测到外部改名",
                     last_observed_title=current_title)
        atomic_json(path, state)
        log(f"locked after external rename: {session_id}")
        return {"status": "manual_title"}
    if state.get("locked"):
        return {"status": "locked"}

    current_fingerprint = fingerprint([users, assistants])
    if state.get("last_fingerprint") == current_fingerprint:
        return {"status": "unchanged"}

    project_hint = Path(cwd).name if cwd else ""
    prompt = build_prompt(users, assistants, current_title, project_hint, config["max_title_length"])
    candidate, usage = None, {}
    # 模型调用失败时重试；失败不阻塞会话。
    # 总耗时必须留在 hook 超时内，否则 Claude Code 会丢弃整个结果。
    for attempt in range(2):
        try:
            candidate, usage = call_model(prompt, config)
            break
        except (RuntimeError, ValueError) as exc:
            log(f"model failed (attempt {attempt + 1}): {session_id}: {exc}")
            if attempt < 1:
                time.sleep(2)
    if candidate is None:
        return {"status": "model_failed"}

    candidate = validate_candidate(candidate, current_title or "", config["max_title_length"], is_linked_worktree(cwd))
    state.update(
        last_fingerprint=current_fingerprint,
        last_observed_title=current_title,
        updated_at=int(time.time()),
        usage=usage,
    )
    if candidate["action"] == "rename":
        # 记录插件自己写下的标题：后续轮次据此区分「用户改名」与「本插件改名」。
        state["last_generated_title"] = candidate["title"]
    atomic_json(path, state)

    if candidate["action"] != "rename":
        log(f"kept: {session_id} ({candidate['reason']})")
        return {"status": "kept", "title": current_title}

    log(f"rename: {session_id} -> {candidate['title']} ({candidate['reason']})")
    return {"status": "renamed", "title": candidate["title"]}


def main() -> int:
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    payload = {}
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}

    session_id = payload.get("session_id") or payload.get("sessionId") or ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    cwd = payload.get("cwd") or ""
    prompt = payload.get("prompt") or ""

    result = {"status": "skipped"}
    if session_id and transcript_path:
        try:
            result = process(session_id, transcript_path, cwd, prompt)
        except Exception as exc:  # noqa: BLE001 - hook 永不阻塞会话
            log(f"error: {session_id}: {exc}")
            result = {"status": "error", "error": str(exc)[:200]}

    # 只有确定要改名时才输出 sessionTitle；其余情况返回空对象。
    if result.get("status") == "renamed" and result.get("title"):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "sessionTitle": result["title"],
            }
        }
    else:
        output = {}
    sys.stdout.write(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
