"""
測試：Webhook 轉送紀錄、自動重試、手動重送。
"""
import json
import time
import unittest
from unittest import mock

import localconfig as cfg
import webhook_delivery as wd
from helpers import app_headers, fresh_db, make_bot, make_user, platform_app
from localbot.utils import check_signature

EVENT_BODY = json.dumps({"destination": "default", "events": [{
    "type": "message", "replyToken": "r1", "source": {"type": "user", "userId": "u1"},
    "message": {"id": "m1", "type": "text", "text": "你好"}}]}, ensure_ascii=False)


class Base(unittest.TestCase):
    def setUp(self):
        fresh_db(f"wd_{self._testMethodName}")
        platform_app.app.config["TESTING"] = True
        self.client = platform_app.app.test_client()
        self.calls = []  # (body dict, signature)
        self.script = []  # 依序回傳的 (status, error)；用完回 200
        self.urls = []

        def fake_forward(bot, body, signature):
            self.assertTrue(check_signature(bot["channel_secret"], body, signature))
            self.calls.append(json.loads(body))
            self.urls.append(bot["webhook_url"])
            status, error = self.script.pop(0) if self.script else (200, None)
            wd.forward_state.error = error
            wd.forward_state.snippet = "oops" if status >= 400 and not error else None
            return status

        p = mock.patch.object(platform_app, "forward_to_bot", side_effect=fake_forward)
        p.start()
        self.addCleanup(p.stop)
        d = mock.patch.object(cfg, "WEBHOOK_RETRY_DELAYS", [10, 60, 300])
        d.start()
        self.addCleanup(d.stop)

    def row(self, did=1):
        return platform_app.db.get_delivery(did)


class TestDeliver(Base):
    def test_success_is_logged(self):
        r = wd.deliver("default", EVENT_BODY)
        self.assertTrue(r["ok"])
        row = self.row()
        self.assertEqual((row["state"], row["attempts"], row["user_id"], row["event_type"]),
                         ("success", 1, "u1", "message"))
        self.assertTrue(row["event_id"])
        self.assertEqual(self.calls[0]["events"][0]["deliveryContext"], {"isRedelivery": False})

    def test_event_ids_added_only_when_missing(self):
        body = json.dumps({"events": [{"type": "message", "webhookEventId": "ABC", "deliveryContext": {"isRedelivery": False}}]})
        self.assertEqual(wd.with_event_ids(body), body)
        self.assertEqual(wd.with_event_ids("not json"), "not json")
        out = json.loads(wd.with_event_ids(json.dumps({"events": [{"type": "x"}]})))
        self.assertTrue(out["events"][0]["webhookEventId"])

    def test_retry_schedule_then_dead(self):
        self.script = [(503, None)] * 10
        r = wd.deliver("default", EVENT_BODY)
        self.assertEqual(r["state"], "retrying")
        self.assertIn("HTTP 503", self.row()["last_error"])
        t0 = self.row()["next_attempt_at"]
        # 尚未到期不處理
        self.assertEqual(wd.process_due(now_ms=t0 - 1000), 0)
        expected = [10, 60, 300]
        now = t0
        for i, delay in enumerate(expected[1:] + [None]):
            self.assertEqual(wd.process_due(now_ms=now), 1)
            row = self.row()
            if delay is None:
                self.assertEqual(row["state"], "dead")
                self.assertIsNone(row["next_attempt_at"])
            else:
                self.assertEqual(row["state"], "retrying")
                self.assertAlmostEqual(row["next_attempt_at"] - int(time.time() * 1000), delay * 1000, delta=3000)
                now = row["next_attempt_at"]
        self.assertEqual(row["attempts"], 4)  # 第一次 + 3 次重試
        self.assertEqual(len(self.calls), 4)
        # 重送的事件：同一個 webhookEventId、isRedelivery=true
        ids = {c["events"][0]["webhookEventId"] for c in self.calls}
        self.assertEqual(len(ids), 1)
        self.assertEqual([c["events"][0]["deliveryContext"]["isRedelivery"] for c in self.calls],
                         [False, True, True, True])

    def test_retry_recovers(self):
        self.script = [(500, None), (200, None)]
        wd.deliver("default", EVENT_BODY)
        self.assertEqual(wd.process_due(now_ms=self.row()["next_attempt_at"]), 1)
        self.assertEqual(self.row()["state"], "success")
        self.assertEqual(wd.process_due(now_ms=int(time.time() * 1000) + 10 ** 9), 0)

    def test_connection_error_is_retryable_and_has_no_status(self):
        self.script = [(500, "ConnectionError: refused")]
        r = wd.deliver("default", EVENT_BODY)
        self.assertEqual(r["state"], "retrying")
        row = self.row()
        self.assertIsNone(row["last_status"])
        self.assertIn("refused", row["last_error"])

    def test_non_retryable_4xx_goes_dead_immediately(self):
        self.script = [(400, None)]
        r = wd.deliver("default", EVENT_BODY)
        self.assertEqual(r["state"], "dead")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("oops", self.row()["last_error"])
        for status in (408, 429):
            self.script = [(status, None)]
            self.assertEqual(wd.deliver("default", EVENT_BODY)["state"], "retrying")

    def test_retry_disabled(self):
        with mock.patch.object(cfg, "WEBHOOK_RETRY_DELAYS", []):
            self.script = [(502, None)]
            self.assertEqual(wd.deliver("default", EVENT_BODY)["state"], "dead")

    def test_manual_resend(self):
        self.script = [(400, None)]
        wd.deliver("default", EVENT_BODY)
        self.script = [(500, None)]
        res, code = wd.resend(1)  # 手動重送失敗 → dead，不再自動重試
        self.assertIsNone(code)
        self.assertFalse(res["ok"])
        self.assertEqual(self.row()["state"], "dead")
        att = platform_app.db.list_attempts(1)
        self.assertEqual([a["manual"] for a in att], [0, 1])
        res, _ = wd.resend(1)  # 這次成功
        self.assertTrue(res["ok"])
        self.assertEqual(self.row()["state"], "success")
        self.assertEqual(wd.resend(999), (None, "not_found"))

    def test_resend_busy(self):
        wd.deliver("default", EVENT_BODY)
        self.assertTrue(platform_app.db.claim_delivery(1, only_due=False))  # 模擬別人正在送
        self.assertEqual(wd.resend(1), (None, "busy"))

    def test_resend_all_dead_goes_through_queue(self):
        self.script = [(400, None), (400, None)]
        wd.deliver("default", EVENT_BODY)
        wd.deliver("default", EVENT_BODY)
        self.assertEqual(wd.resend_all_dead(), 2)
        self.assertEqual(platform_app.db.delivery_counts()["retrying"], 2)
        self.script = [(200, None), (500, None)]
        self.assertEqual(wd.process_due(), 2)
        self.assertEqual({self.row(1)["state"], self.row(2)["state"]}, {"success", "dead"})  # 手動：失敗不再自動重試

    def test_recover_sending_after_restart(self):
        wd.deliver("default", EVENT_BODY)
        platform_app.db.claim_delivery(1, only_due=False)  # 狀態卡在 sending
        self.assertEqual(platform_app.db.recover_sending(), 1)
        self.assertEqual(self.row()["state"], "retrying")
        self.assertEqual(wd.process_due(), 1)

    def test_forward_exception_does_not_escape(self):
        with mock.patch.object(platform_app, "forward_to_bot", side_effect=RuntimeError("boom")):
            r = wd.deliver("default", EVENT_BODY)
        self.assertEqual(r["state"], "retrying")
        self.assertIn("boom", self.row()["last_error"])

    def test_purge_keeps_pending_retries(self):
        self.script = [(500, None)]
        wd.deliver("default", EVENT_BODY)  # retrying
        wd.deliver("default", EVENT_BODY)  # success
        res = platform_app.db.purge_logs(int(time.time() * 1000) + 1000)
        self.assertEqual(res["deliveries"], 1)
        self.assertIsNotNone(self.row(1))
        self.assertIsNone(self.row(2))
        self.assertEqual(platform_app.db.list_attempts(2), [])


class TestPerBot(Base):
    def test_uses_each_bots_own_url_and_secret(self):
        make_bot("shop", webhook_url="http://shop.invalid/hook")
        wd.deliver("default", EVENT_BODY)
        wd.deliver("shop", EVENT_BODY.replace('"default"', '"shop"'))
        self.assertEqual(self.urls, [platform_app.db.get_bot("default")["webhook_url"], "http://shop.invalid/hook"])
        self.assertEqual([self.row(1)["bot_id"], self.row(2)["bot_id"]], ["default", "shop"])
        self.assertEqual(platform_app.db.delivery_counts("shop")["success"], 1)
        self.assertEqual(len(platform_app.db.list_deliveries(bot_id="shop")["deliveries"]), 1)

    def test_deleted_or_disabled_bot_goes_dead_without_forwarding(self):
        make_bot("shop")
        self.script = [(500, None)]
        wd.deliver("shop", EVENT_BODY)  # retrying
        platform_app.db.update_bot("shop", enabled=False)
        self.assertEqual(wd.process_due(now_ms=self.row()["next_attempt_at"]), 1)
        self.assertEqual(self.row()["state"], "dead")
        self.assertIn("Bot", self.row()["last_error"])
        self.assertEqual(len(self.calls), 1)
        platform_app.db.update_bot("shop", enabled=True)  # 重新啟用後可手動重送
        res, _ = wd.resend(1)
        self.assertTrue(res["ok"])

    def test_resend_uses_updated_webhook_url(self):
        make_bot("shop", webhook_url="http://old.invalid/hook")
        self.script = [(400, None)]
        wd.deliver("shop", EVENT_BODY)
        platform_app.db.update_bot("shop", webhook_url="http://new.invalid/hook")
        wd.resend(1)
        self.assertEqual(self.urls, ["http://old.invalid/hook", "http://new.invalid/hook"])


class TestCallbackIntegration(Base):
    def setUp(self):
        super().setUp()
        self.headers = make_user("u1")

    def _post(self):
        return self.client.post("/callback", data=EVENT_BODY, content_type="application/json", headers=self.headers)

    def test_success(self):
        res = self._post()
        self.assertEqual((res.status_code, res.get_data(as_text=True)), (200, "OK"))
        self.assertNotIn("X-LocalBot-Delivery", res.headers)

    def test_retry_queued_returns_200(self):
        self.script = [(500, "ConnectionError: refused")]
        res = self._post()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["X-LocalBot-Delivery"], "queued")
        self.assertEqual(self.row()["state"], "retrying")
        # 訊息本身已存下
        self.assertEqual(len(platform_app.db.get_messages("default", "u1")), 1)

    def test_non_retryable_returns_502(self):
        self.script = [(404, None)]
        res = self._post()
        self.assertEqual(res.status_code, 502)
        self.assertIn("404", res.get_json()["message"])

    def test_retry_disabled_returns_502(self):
        with mock.patch.object(cfg, "WEBHOOK_RETRY_DELAYS", []):
            self.script = [(500, None)]
            self.assertEqual(self._post().status_code, 502)


class TestAsyncCallback(Base):
    """App 1.4 的快速送出：X-LocalBot-Async: 1 → 先回 App，背景依序轉送，失敗用 Socket.IO 通知。"""

    def setUp(self):
        super().setUp()
        self.headers = dict(make_user("u1"), **{"X-LocalBot-Async": "1"})
        self.emitted = []
        e = mock.patch.object(platform_app.socketio, "emit",
                              side_effect=lambda ev, data, room=None: self.emitted.append((ev, data, room)))
        e.start()
        self.addCleanup(e.stop)
        platform_app.connected_users["u1"] = {"sid1"}
        self.addCleanup(platform_app.connected_users.pop, "u1", None)
        # 背景工作改成先收集起來，由測試決定何時執行（模擬「先回 App、之後才轉送」）
        self.jobs = []
        b = mock.patch.object(platform_app, "run_in_background", side_effect=lambda f, *a: self.jobs.append((f, a)))
        b.start()
        self.addCleanup(b.stop)

    def _post(self, body=EVENT_BODY):
        return self.client.post("/callback", data=body, content_type="application/json", headers=self.headers)

    def _run_jobs(self):
        while self.jobs:
            f, a = self.jobs.pop(0)
            f(*a)

    def test_returns_before_forwarding(self):
        res = self._post()
        self.assertEqual((res.status_code, res.headers["X-LocalBot-Delivery"]), (200, "async"))
        self.assertEqual(self.calls, [])  # 還沒轉送
        self.assertEqual(len(platform_app.db.get_messages("default", "u1")), 1)  # 但訊息已存下
        self._run_jobs()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.row()["state"], "success")
        self.assertEqual(self.emitted, [])

    def test_keeps_order_per_user(self):
        for i in range(3):
            body = EVENT_BODY.replace('"m1"', f'"m{i}"').replace("你好", f"第{i}則")
            self.assertEqual(self._post(body).status_code, 200)
        self.assertEqual(len(self.jobs), 1)  # 同一位使用者只開一條背景工作
        self._run_jobs()
        texts = [c["events"][0]["message"]["text"] for c in self.calls]
        self.assertEqual(texts, ["第0則", "第1則", "第2則"])
        self.assertEqual(platform_app.app_deliveries.pending(), 0)

    def test_non_retryable_notifies_app(self):
        self.script = [(404, None)]
        self._post()
        self._run_jobs()
        self.assertEqual(len(self.emitted), 1)
        event, data, room = self.emitted[0]
        self.assertEqual((event, room, data["botId"], data["messageIds"]), ("delivery_failed", "u1", "default", ["m1"]))
        self.assertIn("404", data["reason"])

    def test_retryable_does_not_notify(self):
        self.script = [(500, "ConnectionError: refused")]
        self._post()
        self._run_jobs()
        self.assertEqual(self.row()["state"], "retrying")
        self.assertEqual(self.emitted, [])

    def test_auth_still_checked_synchronously(self):
        self.headers["X-LocalBot-Token"] = "lbu_wrong"
        self.assertEqual(self._post().status_code, 401)
        self.assertEqual(self.jobs, [])


class TestConfig(unittest.TestCase):
    def test_parse_delays(self):
        self.assertEqual(cfg._parse_delays("1, 5,30", [9]), [1, 5, 30])
        self.assertEqual(cfg._parse_delays("", [9]), [])
        self.assertEqual(cfg._parse_delays("abc", [9]), [9])
        self.assertEqual(cfg._parse_delays("10,-5", [9]), [9])


if __name__ == "__main__":
    unittest.main()
