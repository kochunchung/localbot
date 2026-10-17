"""
測試：AI 產生訊息（排程推播用）——金鑰、提示詞變數、Claude / OpenAI 回應解析、排程執行、後台 API。
不會真的連線到 AI 服務（requests.post 全部替換掉）。
"""
import json
import os
import time
import unittest
from datetime import datetime
from unittest import mock

import ai_generate as ai
import localconfig as cfg
import scheduled_push as sp
from helpers import platform_app
from test_scheduled_push import AdminApi, Base

AI_MSG = {"type": "ai", "provider": "claude", "prompt": "整理 {yesterday} 美股", "webSearch": True}


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self):
        return self._data


def claude_reply(text, preamble=True, stop="end_turn"):
    blocks = []
    if preamble:
        blocks += [{"type": "text", "text": "我來搜尋一下。"},
                   {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "美股"}},
                   {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []}]
    blocks.append({"type": "text", "text": text})
    return FakeResponse(200, {"content": blocks, "stop_reason": stop})


class KeyEnv(unittest.TestCase):
    """每個測試用自己的金鑰檔，並清掉可能存在的環境變數。"""

    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for p in ai.PROVIDERS.values():
            for name in p["env"]:
                os.environ.pop(name, None)
        path = os.path.join(os.path.dirname(cfg.SECRETS_FILE), f"ai_{self._testMethodName}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ADMIN_PASSWORD": cfg.ADMIN_PASSWORD}, f)
        s = mock.patch.object(cfg, "SECRETS_FILE", path)
        s.start()
        self.addCleanup(s.stop)
        self.calls = []
        self.replies = []

        def fake_post(url, headers=None, json=None, timeout=None):
            self.calls.append({"url": url, "headers": headers, "json": json})
            return self.replies.pop(0)

        r = mock.patch.object(ai.requests, "post", side_effect=fake_post)
        r.start()
        self.addCleanup(r.stop)


class TestGenerate(KeyEnv):
    def test_missing_key(self):
        with self.assertRaises(ai.AIError) as cm:
            ai.generate(AI_MSG)
        self.assertIn("API 金鑰", str(cm.exception))
        self.assertEqual(self.calls, [])

    def test_key_from_file_and_env(self):
        ai.save_key("claude", "sk-ant-file-0000000000000000000abcd")
        st = ai.key_status()["claude"]
        self.assertEqual((st["configured"], st["source"], st["hint"]), (True, "file", "…abcd"))
        self.assertFalse(ai.key_status()["openai"]["configured"])
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-env-1111111111111111111wxyz"
        self.assertEqual(ai.key_status()["claude"]["source"], "env")
        with self.assertRaises(PermissionError):
            ai.save_key("claude", "x" * 30)
        del os.environ["ANTHROPIC_API_KEY"]
        ai.save_key("claude", "")
        self.assertFalse(ai.key_status()["claude"]["configured"])
        with open(cfg.SECRETS_FILE, encoding="utf-8") as f:
            self.assertIn("ADMIN_PASSWORD", json.load(f))  # 其他金鑰不受影響

    def test_claude_request_and_text_after_search(self):
        ai.save_key("claude", "sk-ant-test-000000000000000000000000")
        self.replies = [claude_reply("・S&P 500 **上漲** 1.2%")]
        text = ai.generate(AI_MSG, now=datetime(2030, 3, 5, 8, 0))
        self.assertEqual(text, "・S&P 500 上漲 1.2%")  # 去掉開場白與 Markdown 粗體
        call = self.calls[0]
        self.assertEqual(call["url"], ai.ANTHROPIC_URL)
        self.assertEqual(call["headers"]["x-api-key"], "sk-ant-test-000000000000000000000000")
        body = call["json"]
        self.assertEqual(body["model"], ai.PROVIDERS["claude"]["default_model"])
        self.assertEqual(body["tools"][0]["type"], "web_search_20250305")
        self.assertIn("2030-03-04（星期一）", body["messages"][0]["content"])  # {yesterday}
        self.assertIn("繁體中文", body["system"])

    def test_claude_pause_turn_continues(self):
        ai.save_key("claude", "sk-ant-test-000000000000000000000000")
        self.replies = [claude_reply("", stop="pause_turn"), claude_reply("完成", preamble=False)]
        self.assertEqual(ai.generate(AI_MSG), "完成")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1]["json"]["messages"][-1]["role"], "assistant")

    def test_openai_request_and_parse(self):
        ai.save_key("openai", "sk-openai-test-00000000000000000000")
        self.replies = [FakeResponse(200, {"output": [
            {"type": "web_search_call", "id": "ws1", "status": "completed"},
            {"type": "message", "content": [{"type": "output_text", "text": "今天天氣晴", "annotations": []}]}]})]
        text = ai.generate({"type": "ai", "provider": "openai", "prompt": "今天 {today}", "model": "gpt-test"})
        self.assertEqual(text, "今天天氣晴")
        body = self.calls[0]["json"]
        self.assertEqual((body["model"], "tools" in body), ("gpt-test", False))
        self.assertEqual(self.calls[0]["headers"]["Authorization"], "Bearer sk-openai-test-00000000000000000000")

    def test_http_errors_are_friendly(self):
        ai.save_key("claude", "sk-ant-test-000000000000000000000000")
        for status, word in ((401, "金鑰無效"), (429, "額度"), (404, "模型"), (500, "HTTP 500")):
            self.replies = [FakeResponse(status, {"error": {"message": "boom"}})]
            with self.assertRaises(ai.AIError) as cm:
                ai.generate(AI_MSG)
            self.assertIn(word, str(cm.exception))

    def test_validation(self):
        ok, err = ai.validate_ai_message({"type": "ai", "provider": "claude", "prompt": " 嗨 "})
        self.assertIsNone(err)
        self.assertEqual(ok, {"type": "ai", "provider": "claude", "prompt": "嗨", "webSearch": False,
                              "maxChars": ai.DEFAULT_MAX_CHARS})
        for bad in ({"provider": "gemini", "prompt": "x"}, {"provider": "claude", "prompt": ""},
                    {"provider": "claude", "prompt": "x" * 5000}, {"provider": "claude", "prompt": "x", "model": "a b"},
                    {"provider": "claude", "prompt": "x", "webSearch": "yes"},
                    {"provider": "claude", "prompt": "x", "maxChars": 10}):
            self.assertIsNotNone(ai.validate_ai_message(bad)[1], bad)


class TestScheduleWithAI(KeyEnv, Base):
    def setUp(self):
        super().setUp()
        ai.save_key("claude", "sk-ant-test-000000000000000000000000")

    def test_generates_once_and_sends_text_to_everyone(self):
        sid = self.make(messages=[AI_MSG, {"type": "text", "text": "祝投資順利"}])
        self.replies = [claude_reply("美股摘要")]
        res = sp.run_now(sid)
        self.assertEqual((res["sent"], res["error"]), (3, None))
        self.assertEqual(len(self.calls), 1)  # 只呼叫 AI 一次
        for _, msgs in self.delivered:
            self.assertEqual(msgs, [{"type": "text", "text": "美股摘要"}, {"type": "text", "text": "祝投資順利"}])
        # 資料庫裡的排程仍是 AI 設定，下次會重新產生
        self.assertEqual(platform_app.db.get_schedule(sid)["messages"][0]["type"], "ai")

    def test_ai_failure_sends_nothing_and_records_error(self):
        sid = self.make(messages=[AI_MSG])
        self.replies = [FakeResponse(401, {"error": {"message": "invalid x-api-key"}})]
        res = sp.run_now(sid)
        self.assertEqual(res["sent"], 0)
        self.assertIn("AI 產生失敗", res["error"])
        self.assertEqual(self.delivered, [])

    def test_process_due_runs_ai_in_background(self):
        now = int(time.time() * 1000)
        sid = self.make(messages=[AI_MSG], next_run=now - 1000)
        jobs = []
        with mock.patch.object(platform_app, "run_in_background", side_effect=lambda f, *a: jobs.append((f, a))):
            self.assertEqual(sp.process_due(now), 1)
        self.assertEqual(self.delivered, [])  # 還沒執行，排程迴圈不被擋住
        self.replies = [claude_reply("背景完成")]
        f, a = jobs[0]
        f(*a)
        self.assertEqual(len(self.delivered), 3)
        self.assertEqual(platform_app.db.get_schedule(sid)["last_result"]["kind"], "auto")


class TestAIAdminApi(KeyEnv, AdminApi):
    def test_status_save_and_clear_key(self):
        r = self.call("get", "/ai").get_json()
        self.assertFalse(r["providers"]["claude"]["configured"])
        self.assertIn("{yesterday}", r["variables"])
        res = self.call("put", "/ai/keys/claude", {"key": "sk-ant-api-0000000000000000000000zz"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["providers"]["claude"]["hint"], "…00zz")
        self.assertNotIn("sk-ant-api", res.get_data(as_text=True))  # 不回傳完整金鑰
        self.assertEqual(self.call("put", "/ai/keys/claude", {"key": "short"}).status_code, 400)
        self.assertEqual(self.call("put", "/ai/keys/gemini", {"key": "x" * 30}).status_code, 404)
        self.assertFalse(self.call("put", "/ai/keys/claude", {"key": ""}).get_json()["providers"]["claude"]["configured"])
        anon = platform_app.app.test_client()
        self.assertEqual(anon.get("/admin/api/ai").status_code, 401)
        self.assertEqual(self.client.put("/admin/api/ai/keys/claude", json={"key": "x" * 30}).status_code, 403)  # 缺 CSRF

    def test_preview(self):
        res = self.call("post", "/ai/preview", {"provider": "claude", "prompt": "hi"})
        self.assertEqual(res.status_code, 502)
        self.assertIn("API 金鑰", res.get_json()["error"])
        ai.save_key("claude", "sk-ant-test-000000000000000000000000")
        self.replies = [claude_reply("試產生內容")]
        res = self.call("post", "/ai/preview", {"provider": "claude", "prompt": "hi", "webSearch": True})
        self.assertEqual(res.get_json()["text"], "試產生內容")
        self.assertEqual(self.delivered, [])  # 試產生不會傳給任何人

    def test_schedule_api_accepts_ai_message(self):
        res = self.call("post", "/schedules", self.payload(messages=[dict(AI_MSG, extra="dropped")]))
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        saved = res.get_json()["messages"][0]
        self.assertEqual(saved, {"type": "ai", "provider": "claude", "prompt": "整理 {yesterday} 美股",
                                 "webSearch": True, "maxChars": ai.DEFAULT_MAX_CHARS})
        bad = self.call("post", "/schedules", self.payload(messages=[{"type": "ai", "provider": "claude", "prompt": ""}]))
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
