"""
測試：排程推播（時間計算、驗證、執行、錯過處理）與後台 API（排程 + Webhook 日誌）。
"""
import json
import time
import unittest
from datetime import datetime
from unittest import mock

import admin_panel
import localconfig as cfg
import scheduled_push as sp
import webhook_delivery as wd
from helpers import fresh_db, make_bot, make_user, platform_app


def ms(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi).timestamp() * 1000)


def local(ts):
    return datetime.fromtimestamp(ts / 1000)


class TestComputeNext(unittest.TestCase):
    def test_once(self):
        at = ms(2030, 1, 1, 9)
        self.assertEqual(sp.compute_next({"type": "once", "at": at}, at - 1), at)
        self.assertIsNone(sp.compute_next({"type": "once", "at": at}, at))

    def test_daily(self):
        s = {"type": "daily", "time": "09:30"}
        self.assertEqual(sp.compute_next(s, ms(2030, 3, 5, 8)), ms(2030, 3, 5, 9, 30))
        self.assertEqual(sp.compute_next(s, ms(2030, 3, 5, 9, 30)), ms(2030, 3, 6, 9, 30))  # 嚴格晚於
        self.assertEqual(sp.compute_next(s, ms(2030, 12, 31, 10)), ms(2031, 1, 1, 9, 30))

    def test_weekly(self):
        # 2030-03-04 是週一
        self.assertEqual(datetime(2030, 3, 4).weekday(), 0)
        s = {"type": "weekly", "days": [0, 4], "time": "18:00"}
        self.assertEqual(sp.compute_next(s, ms(2030, 3, 4, 19)), ms(2030, 3, 8, 18))  # 週五
        self.assertEqual(sp.compute_next(s, ms(2030, 3, 8, 19)), ms(2030, 3, 11, 18))  # 下週一

    def test_monthly_clamps_to_month_end(self):
        s = {"type": "monthly", "day": 31, "time": "08:00"}
        self.assertEqual(sp.compute_next(s, ms(2030, 1, 31, 9)), ms(2030, 2, 28, 8))
        self.assertEqual(sp.compute_next(s, ms(2030, 2, 28, 9)), ms(2030, 3, 31, 8))
        self.assertEqual(sp.compute_next(s, ms(2030, 3, 31, 9)), ms(2030, 4, 30, 8))
        self.assertEqual(sp.compute_next({"type": "monthly", "day": 15, "time": "08:00"}, ms(2030, 1, 16)),
                         ms(2030, 2, 15, 8))

    def test_preview(self):
        out = sp.preview({"type": "daily", "time": "10:00"}, 3, ms(2030, 1, 1, 12))
        self.assertEqual([local(t).day for t in out], [2, 3, 4])
        self.assertEqual(sp.preview({"type": "once", "at": 5}, 3, 10), [])


class Base(unittest.TestCase):
    def setUp(self):
        fresh_db(f"sp_{self._testMethodName}")
        platform_app.app.config["TESTING"] = True
        admin_panel.reset_login_limiter()
        self.client = platform_app.app.test_client()
        self.delivered = []
        p = mock.patch.object(platform_app, "deliver_to_client",
                              side_effect=lambda bot_id, uid, msgs: self.delivered.append((uid, msgs)) or ["id"] * len(msgs))
        p.start()
        self.addCleanup(p.stop)
        for uid in ("a", "b", "c"):
            make_user(uid, name=uid.upper())

    def make(self, schedule=None, target=None, enabled=True, next_run=None, messages=None, bot_id="default"):
        schedule = schedule or {"type": "daily", "time": "09:00"}
        nxt = next_run if next_run is not None else sp.compute_next(schedule, int(time.time() * 1000))
        return platform_app.db.create_schedule(
            bot_id, "測試", messages or [{"type": "text", "text": "早安"}], target or {"type": "broadcast"},
            schedule, enabled, nxt)


class TestValidation(Base):
    def test_schedule(self):
        ok = lambda s: self.assertIsNone(sp.validate_schedule(s)[1], s)  # noqa: E731
        bad = lambda s: self.assertIsNotNone(sp.validate_schedule(s)[1], s)  # noqa: E731
        ok({"type": "daily", "time": "00:00"})
        ok({"type": "weekly", "days": [6, 0, 6], "time": "23:59"})
        ok({"type": "monthly", "day": 31, "time": "12:00"})
        ok({"type": "once", "at": ms(2030, 1, 1)})
        self.assertEqual(sp.validate_schedule({"type": "weekly", "days": [6, 0, 6], "time": "23:59"})[0]["days"], [0, 6])
        for s in (None, {}, {"type": "cron"}, {"type": "daily", "time": "24:00"}, {"type": "daily", "time": "9:00"},
                  {"type": "weekly", "days": [], "time": "09:00"}, {"type": "weekly", "days": [7], "time": "09:00"},
                  {"type": "weekly", "days": [True], "time": "09:00"}, {"type": "monthly", "day": 0, "time": "09:00"},
                  {"type": "monthly", "day": 32, "time": "09:00"}, {"type": "once"}, {"type": "once", "at": "x"},
                  {"type": "once", "at": True}):
            bad(s)

    def test_target(self):
        self.assertEqual(sp.validate_target({"type": "users", "userIds": ["a", "a", "b"]})[0]["userIds"], ["a", "b"])
        for t in (None, {"type": "all"}, {"type": "users"}, {"type": "users", "userIds": []},
                  {"type": "users", "userIds": ["../x"]}, {"type": "users", "userIds": [1]},
                  {"type": "users", "userIds": [f"u{i}" for i in range(501)]}):
            self.assertIsNotNone(sp.validate_target(t)[1], t)

    def test_payload(self):
        base = {"botId": "default", "name": "x", "text": "hi", "target": {"type": "broadcast"}, "schedule": {"type": "daily", "time": "09:00"}}
        fields, err = sp.validate_payload(base)
        self.assertIsNone(err)
        self.assertEqual(fields["messages"], [{"type": "text", "text": "hi"}])
        self.assertEqual(fields["bot_id"], "default")
        for patch in ({"botId": None}, {"botId": "nope"}, {"name": " "}, {"name": "x" * 61}, {"text": " "}, {"text": "x" * 5001},
                      {"messages": []}, {"messages": [{"type": "text", "text": "a"}] * 6},
                      {"messages": [{"nope": 1}]}, {"enabled": "yes"}):
            data = dict(base)
            data.pop("text") if "messages" in patch else None
            data.update(patch)
            self.assertIsNotNone(sp.validate_payload(data)[1], patch)
        data = dict(base, text=None, messages=[{"type": "flex", "altText": "a", "contents": {"type": "bubble"}}])
        self.assertIsNone(sp.validate_payload(data)[1])  # 任意 LINE 訊息


class TestExecute(Base):
    def test_broadcast_skips_blocked(self):
        platform_app.db.set_blocked("default", "c", True)
        sid = self.make()
        res = sp.run_now(sid)
        self.assertEqual((res["sent"], res["skipped"], res["error"]), (2, 0, None))
        self.assertEqual({u for u, _ in self.delivered}, {"a", "b"})
        row = platform_app.db.get_schedule(sid)
        self.assertEqual(row["run_count"], 1)
        self.assertEqual(row["last_result"]["kind"], "manual")
        self.assertIsNotNone(row["next_run_at"])  # 手動執行不影響下次

    def test_selected_users(self):
        platform_app.db.set_blocked("default", "b", True)
        sid = self.make(target={"type": "users", "userIds": ["a", "b", "ghost"]})
        res = sp.run_now(sid)
        self.assertEqual((res["sent"], res["skipped"]), (1, 2))
        self.assertEqual([u for u, _ in self.delivered], ["a"])

    def test_delivery_error_is_recorded_and_continues(self):
        def flaky(bot_id, uid, msgs):
            if uid == "a":
                raise RuntimeError("boom")
            self.delivered.append(uid)
        with mock.patch.object(platform_app, "deliver_to_client", side_effect=flaky):
            res = sp.run_now(self.make())
        self.assertEqual((res["sent"], res["skipped"]), (2, 1))
        self.assertIn("boom", res["error"])

    def test_only_targets_members_of_its_bot(self):
        make_bot("shop")
        make_user("s1", bots=("shop",))
        make_user("both", bots=("default", "shop"))
        res = sp.run_now(self.make(bot_id="shop"))
        self.assertEqual({u for u, _ in self.delivered}, {"s1", "both"})
        self.assertEqual(res["sent"], 2)
        self.delivered.clear()
        res = sp.run_now(self.make(target={"type": "users", "userIds": ["a", "s1"]}))  # s1 不是 default 的好友
        self.assertEqual((res["sent"], res["skipped"]), (1, 1))
        self.assertEqual([u for u, _ in self.delivered], ["a"])

    def test_disabled_or_deleted_bot_records_error(self):
        make_bot("shop")
        sid = self.make(bot_id="shop")
        platform_app.db.update_bot("shop", enabled=False)
        res = sp.run_now(sid)
        self.assertEqual(res["sent"], 0)
        self.assertIn("Bot", res["error"])
        self.assertEqual(self.delivered, [])

    def test_process_due_runs_once_and_advances(self):
        now = ms(2030, 5, 1, 9, 0, ) + 5000
        sid = self.make(next_run=ms(2030, 5, 1, 9, 0))
        self.assertEqual(sp.process_due(now_ms=now), 1)
        self.assertEqual(len(self.delivered), 3)
        row = platform_app.db.get_schedule(sid)
        self.assertEqual(row["next_run_at"], ms(2030, 5, 2, 9, 0))
        self.assertEqual(row["last_result"]["kind"], "auto")
        self.assertEqual(sp.process_due(now_ms=now), 0)  # 同一時間點不會再跑
        self.assertEqual(len(self.delivered), 3)

    def test_claim_is_atomic(self):
        sid = self.make(next_run=1000)
        self.assertTrue(platform_app.db.claim_schedule(sid, 1000, 2000))
        self.assertFalse(platform_app.db.claim_schedule(sid, 1000, 3000))

    def test_once_finishes(self):
        at = ms(2030, 5, 1, 9)
        sid = self.make(schedule={"type": "once", "at": at}, next_run=at)
        sp.process_due(now_ms=at + 1000)
        row = platform_app.db.get_schedule(sid)
        self.assertIsNone(row["next_run_at"])
        self.assertEqual(platform_app.db.due_schedules(at + 10 ** 9), [])
        self.assertEqual(platform_app.db.automation_stats()["schedulesActive"], 0)

    def test_missed_beyond_grace_is_skipped(self):
        due = ms(2030, 5, 1, 9)
        sid = self.make(next_run=due)
        with mock.patch.object(cfg, "SCHEDULE_GRACE_MINUTES", 60):
            sp.process_due(now_ms=due + 3 * 3600 * 1000)
        self.assertEqual(self.delivered, [])
        row = platform_app.db.get_schedule(sid)
        self.assertEqual(row["last_result"]["kind"], "missed")
        self.assertEqual(row["run_count"], 0)
        self.assertEqual(row["next_run_at"], ms(2030, 5, 2, 9))
        self.assertEqual(platform_app.db.list_runs(sid)[0]["kind"], "missed")

    def test_within_grace_still_runs(self):
        due = ms(2030, 5, 1, 9)
        self.make(next_run=due)
        with mock.patch.object(cfg, "SCHEDULE_GRACE_MINUTES", 60):
            sp.process_due(now_ms=due + 30 * 60 * 1000)
        self.assertEqual(len(self.delivered), 3)

    def test_disabled_never_runs(self):
        self.make(enabled=False, next_run=1)
        self.assertEqual(sp.process_due(now_ms=10 ** 13), 0)

    def test_run_history_capped(self):
        sid = self.make()
        for _ in range(55):
            platform_app.db.record_run(sid, "auto", 1, 0, None)
        self.assertEqual(len(platform_app.db.list_runs(sid, 100)), 50)


class TestWorkers(Base):
    def test_start_runs_jobs_and_stops(self):
        import workers
        sid = self.make(next_run=int(time.time() * 1000) - 1000)
        try:
            workers.start(platform_app)
            for _ in range(60):
                if self.delivered:
                    break
                time.sleep(0.1)
        finally:
            workers.stop()
        self.assertEqual(len(self.delivered), 3)
        self.assertEqual(platform_app.db.get_schedule(sid)["run_count"], 1)


class AdminApi(Base):
    def setUp(self):
        super().setUp()
        res = self.client.post("/admin/api/login", json={"password": cfg.ADMIN_PASSWORD})
        self.csrf = res.get_json()["csrf"]

    def call(self, method, path, body=None, auth=True):
        headers = {"X-CSRF-Token": self.csrf} if auth else {}
        return getattr(self.client, method)("/admin/api" + path, json=body, headers=headers)

    def payload(self, **kw):
        base = {"botId": "default", "name": "每日問候", "text": "早安", "target": {"type": "broadcast"},
                "schedule": {"type": "daily", "time": "09:00"}, "enabled": True}
        base.update(kw)
        return base


class TestScheduleApi(AdminApi):
    def test_requires_login_and_csrf(self):
        self.assertEqual(self.client.get("/admin/api/schedules", headers={}).status_code, 200)  # 已登入
        anon = platform_app.app.test_client()
        for method, path in (("get", "/schedules"), ("post", "/schedules"), ("delete", "/schedules/1"),
                             ("post", "/schedules/1/run"), ("get", "/webhook/deliveries"),
                             ("post", "/webhook/deliveries/1/resend"), ("post", "/webhook/deliveries/resend-failed")):
            self.assertEqual(getattr(anon, method)("/admin/api" + path, json={}).status_code, 401, path)
        res = self.client.post("/admin/api/schedules", json=self.payload())  # 缺 CSRF
        self.assertEqual(res.status_code, 403)

    def test_crud(self):
        res = self.call("post", "/schedules", self.payload())
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        sch = res.get_json()
        self.assertEqual((sch["status"], sch["messages"]), ("active", [{"type": "text", "text": "早安"}]))
        self.assertGreater(sch["nextRunAt"], int(time.time() * 1000))
        sid = sch["id"]
        lst = self.call("get", "/schedules").get_json()
        self.assertEqual(len(lst["schedules"]), 1)
        self.assertIn("utcOffsetMinutes", lst)

        res = self.call("put", f"/schedules/{sid}", self.payload(name="新名稱", schedule={"type": "weekly", "days": [1], "time": "10:00"}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["name"], "新名稱")
        self.assertEqual(local(res.get_json()["nextRunAt"]).weekday(), 1)

        # 只改名稱：保留原本的下次執行時間
        before = res.get_json()["nextRunAt"]
        res = self.call("put", f"/schedules/{sid}", self.payload(name="只改名", schedule={"type": "weekly", "days": [1], "time": "10:00"}))
        self.assertEqual(res.get_json()["nextRunAt"], before)

        res = self.call("patch", f"/schedules/{sid}", {"enabled": False})
        self.assertEqual((res.get_json()["status"], res.get_json()["nextRunAt"]), ("paused", None))
        res = self.call("patch", f"/schedules/{sid}", {"enabled": True})
        self.assertEqual(res.get_json()["status"], "active")
        self.assertEqual(self.call("patch", f"/schedules/{sid}", {"enabled": "x"}).status_code, 400)

        self.assertEqual(self.call("delete", f"/schedules/{sid}").status_code, 200)
        self.assertEqual(self.call("get", f"/schedules/{sid}").status_code, 404)
        self.assertEqual(self.call("delete", f"/schedules/{sid}").status_code, 404)

    def test_validation_errors(self):
        past = int(time.time() * 1000) - 60000
        for body in (self.payload(name=""), self.payload(schedule={"type": "daily", "time": "99:99"}),
                     self.payload(schedule={"type": "once", "at": past}), self.payload(target={"type": "users", "userIds": []}),
                     self.payload(text=" ")):
            res = self.call("post", "/schedules", body)
            self.assertEqual(res.status_code, 400, body)
            self.assertIn("error", res.get_json())
        # 已過期的單次排程，若停用則可儲存，但不能啟用
        res = self.call("post", "/schedules", self.payload(schedule={"type": "once", "at": past}, enabled=False))
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.call("patch", f"/schedules/{res.get_json()['id']}", {"enabled": True}).status_code, 400)

    def test_run_now_needs_confirm(self):
        sid = self.call("post", "/schedules", self.payload()).get_json()["id"]
        self.assertEqual(self.call("post", f"/schedules/{sid}/run", {}).status_code, 400)
        self.assertEqual(self.delivered, [])
        res = self.call("post", f"/schedules/{sid}/run", {"confirm": True})
        self.assertEqual(res.get_json()["sent"], 3)
        runs = self.call("get", f"/schedules/{sid}/runs").get_json()["runs"]
        self.assertEqual([r["kind"] for r in runs], ["manual"])
        self.assertEqual(self.call("post", "/schedules/999/run", {"confirm": True}).status_code, 404)

    def test_bot_is_required_and_filterable(self):
        res = self.call("post", "/schedules", {k: v for k, v in self.payload().items() if k != "botId"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.call("post", "/schedules", self.payload(botId="nope")).status_code, 400)
        make_bot("shop", name="商店")
        a = self.call("post", "/schedules", self.payload()).get_json()
        b = self.call("post", "/schedules", self.payload(botId="shop")).get_json()
        self.assertEqual((a["botId"], b["botId"], b["botName"]), ("default", "shop", "商店"))
        self.assertEqual(len(self.call("get", "/schedules").get_json()["schedules"]), 2)
        only = self.call("get", "/schedules?botId=shop").get_json()["schedules"]
        self.assertEqual([x["id"] for x in only], [b["id"]])
        self.assertEqual(self.call("get", "/schedules?botId=nope").status_code, 404)
        # 改成另一個 Bot
        res = self.call("put", f"/schedules/{a['id']}", self.payload(botId="shop"))
        self.assertEqual(res.get_json()["botId"], "shop")

    def test_preview(self):
        res = self.call("post", "/schedules/preview", {"schedule": {"type": "daily", "time": "09:00"}})
        self.assertEqual(len(res.get_json()["next"]), 3)
        self.assertEqual(self.call("post", "/schedules/preview", {"schedule": {"type": "x"}}).status_code, 400)

    def test_stats_include_automation(self):
        self.call("post", "/schedules", self.payload())
        data = self.call("get", "/stats").get_json()
        self.assertEqual(data["schedulesActive"], 1)
        self.assertIsNotNone(data["nextScheduleAt"])
        self.assertEqual((data["webhookRetrying"], data["webhookDead"]), (0, 0))
        self.assertIn("serverTime", data)


class TestWebhookLogApi(AdminApi):
    BODY = json.dumps({"events": [{"type": "message", "source": {"type": "user", "userId": "a"},
                                   "message": {"id": "1", "type": "text", "text": "hello"}}]})

    def setUp(self):
        super().setUp()
        self.script = []

        def fake(bot, body, sig):
            status, err = self.script.pop(0) if self.script else (200, None)
            wd.forward_state.error = err
            wd.forward_state.snippet = None
            return status

        p = mock.patch.object(platform_app, "forward_to_bot", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)

    def test_list_filter_detail_resend(self):
        self.script = [(200, None), (400, None), (503, None)]
        for _ in range(3):
            wd.deliver("default", self.BODY)
        res = self.call("get", "/webhook/deliveries").get_json()
        self.assertEqual([d["state"] for d in res["deliveries"]], ["retrying", "dead", "success"])
        self.assertEqual((res["counts"]["dead"], res["counts"]["retrying"], res["counts"]["success"]), (1, 1, 1))
        self.assertNotIn("body", res["deliveries"][0])
        dead = self.call("get", "/webhook/deliveries?state=dead").get_json()["deliveries"]
        self.assertEqual([d["id"] for d in dead], [2])
        self.assertEqual(len(self.call("get", "/webhook/deliveries?q=a&limit=2").get_json()["deliveries"]), 2)
        self.assertTrue(self.call("get", "/webhook/deliveries?limit=1").get_json()["hasMore"])

        detail = self.call("get", "/webhook/deliveries/2").get_json()
        self.assertIn("hello", detail["body"])
        self.assertEqual(len(detail["attemptLog"]), 1)
        self.assertEqual(detail["attemptLog"][0]["status"], 400)
        self.assertEqual(self.call("get", "/webhook/deliveries/99").status_code, 404)

        res = self.call("post", "/webhook/deliveries/2/resend").get_json()
        self.assertTrue(res["ok"])
        self.assertEqual(self.call("get", "/webhook/deliveries/2").get_json()["state"], "success")
        self.assertEqual(self.call("post", "/webhook/deliveries/99/resend").status_code, 404)

    def test_filter_by_bot(self):
        make_bot("shop", name="商店")
        wd.deliver("default", self.BODY)
        wd.deliver("shop", self.BODY)
        res = self.call("get", "/webhook/deliveries?botId=shop").get_json()
        self.assertEqual([(d["botId"], d["botName"]) for d in res["deliveries"]], [("shop", "商店")])
        self.assertEqual(res["counts"]["success"], 1)
        self.assertEqual(len(self.call("get", "/webhook/deliveries").get_json()["deliveries"]), 2)
        self.assertEqual(self.call("get", "/webhook/deliveries?botId=nope").status_code, 404)

    def test_resend_failed_needs_confirm(self):
        self.script = [(400, None)]
        wd.deliver("default", self.BODY)
        self.assertEqual(self.call("post", "/webhook/deliveries/resend-failed", {}).status_code, 400)
        res = self.call("post", "/webhook/deliveries/resend-failed", {"confirm": True})
        self.assertEqual(res.get_json()["queued"], 1)


if __name__ == "__main__":
    unittest.main()
