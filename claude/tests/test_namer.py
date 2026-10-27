import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("namer", Path(__file__).resolve().parents[1] / "namer.py")
namer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(namer)


class NamerTests(unittest.TestCase):
    def test_git_worktree_and_formatted_title(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / "repo"
            repo.mkdir()
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "init")
            linked = Path(folder) / "linked"
            git("worktree", "add", "-b", "test", str(linked))
            self.assertFalse(namer.is_linked_worktree(str(repo)))
            self.assertTrue(namer.is_linked_worktree(str(linked)))
            candidate = {"action": "rename", "title": "🧩 产品视频｜讲解大纲", "reason": "测试"}
            self.assertEqual(namer.validate_candidate(candidate, "旧标题", 15, True)["title"], "🌳 产品视频｜讲解大纲")
            self.assertEqual(namer.validate_candidate(candidate, "旧标题", 8, True)["action"], "keep")

    def test_config_controls_prompt_and_length(self):
        candidate = {"action": "rename", "title": "🧩 产品视频｜讲解大纲", "reason": "测试"}
        self.assertEqual(namer.validate_candidate(candidate, "旧标题", 15, False)["action"], "rename")
        self.assertEqual(namer.validate_candidate(candidate, "旧标题", 8, False)["action"], "keep")
        self.assertIn('"max_title_length": 8', namer.build_prompt([], [], "", "", 8))
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"CLAUDE_SESSION_NAMER_DATA": folder}):
            self.assertEqual(namer.load_config()["max_title_length"], 15)
            self.assertEqual(namer.load_config()["model"], "claude-haiku-5-5")

    def test_cli_uses_safe_subscription_session(self):
        result = SimpleNamespace(returncode=0, stdout='{"result":"{\\"action\\":\\"rename\\",\\"title\\":\\"🧩 产品｜修复\\",\\"reason\\":\\"目标\\"}","usage":{}}')
        with patch.object(namer.shutil, "which", return_value="claude"), patch.object(namer.subprocess, "run", return_value=result) as run:
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test", "CLAUDECODE": "1"}):
                candidate, _ = namer.call_model("test", {"model": "claude-haiku-5-5", "model_timeout_seconds": 25})
        self.assertEqual(candidate["title"], "🧩 产品｜修复")
        args, options = run.call_args
        for flag in ("--safe-mode", "--tools", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, args[0])
        self.assertNotIn("ANTHROPIC_API_KEY", options["env"])
        self.assertNotIn("CLAUDECODE", options["env"])

    def test_gear_category(self):
        candidate = {"action": "rename", "title": "⚙️ 账号｜配置", "reason": "测试"}
        self.assertEqual(namer.validate_candidate(candidate, "", 15, True)["title"], "🌳 账号｜配置")

if __name__ == "__main__":
    unittest.main()
