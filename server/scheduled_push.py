"""
排程推播：單次 / 每日 / 每週 / 每月，用 Bot 的身分把訊息（任意 LINE 訊息 JSON）送給全體或指定使用者。

時間一律用「伺服器本機時區」（單次的 at 是絕對時間 epoch ms，由瀏覽器換算）。
每次執行前先把 next_run_at 推進到下一次（比較並交換），所以同一個時間點最多執行一次；
伺服器停機錯過的排程：超過寬限時間（LOCALBOT_SCHEDULE_GRACE_MINUTES）就不補送，記為 missed。
"""
import calendar
import logging
import re
import time
from datetime import datetime, timedelta, time as dtime

import ai_generate
import localconfig as cfg

logger = logging.getLogger("LocalBotPlatform")

_ctx = None
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MAX_TARGET_USERS = 500
MAX_NAME_LEN = 60
SCHEDULE_TYPES = ("once", "daily", "weekly", "monthly")


def init(ctx):
    global _ctx
    _ctx = ctx


def _db():
    return _ctx.db


# ----------------------------------------------------------------------------
# 時間計算（純函式）
# ----------------------------------------------------------------------------
def _parse_time(text: str) -> dtime:
    m = TIME_RE.match(text)
    return dtime(int(m.group(1)), int(m.group(2)))


def compute_next(schedule: dict, after_ms: int):
    """回傳嚴格晚於 after_ms 的下一次執行時間（epoch ms）；單次已過則回傳 None。"""
    kind = schedule.get("type")
    if kind == "once":
        at = int(schedule["at"])
        return at if at > after_ms else None
    at_time = _parse_time(schedule["time"])
    start = datetime.fromtimestamp(after_ms / 1000.0)
    for offset in range(0, 400):
        day = (start + timedelta(days=offset)).date()
        if kind == "weekly" and day.weekday() not in schedule["days"]:
            continue
        if kind == "monthly" and day.day != min(int(schedule["day"]), calendar.monthrange(day.year, day.month)[1]):
            continue
        ts = int(datetime.combine(day, at_time).timestamp() * 1000)
        if ts > after_ms:
            return ts
    return None


def preview(schedule: dict, count: int = 3, after_ms=None) -> list:
    t = after_ms if after_ms is not None else int(time.time() * 1000)
    out = []
    for _ in range(count):
        t = compute_next(schedule, t)
        if t is None:
            break
        out.append(t)
    return out


# ----------------------------------------------------------------------------
# 驗證
# ----------------------------------------------------------------------------
def validate_schedule(raw):
    """回傳 (正規化後的 schedule, 錯誤訊息)。"""
    if not isinstance(raw, dict) or raw.get("type") not in SCHEDULE_TYPES:
        return None, "schedule.type 必須是 once / daily / weekly / monthly"
    kind = raw["type"]
    if kind == "once":
        at = raw.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not (0 < at < 4102444800000):
            return None, "單次排程需要有效的時間（at，毫秒時間戳）"
        return {"type": "once", "at": int(at)}, None
    t = raw.get("time")
    if not isinstance(t, str) or not TIME_RE.match(t):
        return None, "time 必須是 HH:MM（24 小時制）"
    if kind == "daily":
        return {"type": "daily", "time": t}, None
    if kind == "weekly":
        days = raw.get("days")
        if (not isinstance(days, list) or not days
                or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days)):
            return None, "weekly 需要 days：0（週一）到 6（週日）的陣列"
        return {"type": "weekly", "days": sorted(set(days)), "time": t}, None
    day = raw.get("day")
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
        return None, "monthly 需要 day：1 到 31（沒有該日的月份會改在月底執行）"
    return {"type": "monthly", "day": day, "time": t}, None


def validate_target(raw):
    if not isinstance(raw, dict):
        return None, "target 必須是物件"
    if raw.get("type") == "broadcast":
        return {"type": "broadcast"}, None
    if raw.get("type") == "users":
        ids = raw.get("userIds")
        if not isinstance(ids, list) or not ids:
            return None, "請至少選擇一位使用者"
        if len(ids) > MAX_TARGET_USERS:
            return None, f"指定使用者最多 {MAX_TARGET_USERS} 位"
        clean = []
        for uid in ids:
            if not isinstance(uid, str) or not _ctx.is_safe_id(uid):
                return None, "userIds 含有無效的 ID"
            if uid not in clean:
                clean.append(uid)
        return {"type": "users", "userIds": clean}, None
    return None, "target.type 必須是 broadcast 或 users"


def validate_payload(data):
    """驗證整個排程請求。回傳 (欄位 dict, 錯誤)。dict 含 name/messages/target/schedule/enabled。"""
    if not isinstance(data, dict):
        return None, "請求格式錯誤"
    bot_id = data.get("botId")
    if not isinstance(bot_id, str) or _db().get_bot(bot_id) is None:
        return None, "請選擇要使用的 Bot"
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "請輸入排程名稱"
    name = name.strip()
    if len(name) > MAX_NAME_LEN:
        return None, f"名稱最多 {MAX_NAME_LEN} 字"
    messages = data.get("messages")
    if messages is None and isinstance(data.get("text"), str):
        messages = [{"type": "text", "text": data["text"]}]
    err = _ctx.validate_messages(messages)
    if err:
        return None, err
    messages = list(messages)
    for i, msg in enumerate(messages):
        if msg["type"] == "ai":  # AI 產生的訊息（執行時才產生內容，見 ai_generate.py）
            clean, err = ai_generate.validate_ai_message(msg)
            if err:
                return None, err
            messages[i] = clean
            continue
        if msg["type"] == "text" and (not isinstance(msg.get("text"), str) or not msg["text"].strip()):
            return None, f"messages[{i}] 文字內容不可為空"
        if msg["type"] == "text" and len(msg["text"]) > 5000:
            return None, "文字訊息最多 5000 字"
    target, err = validate_target(data.get("target"))
    if err:
        return None, err
    schedule, err = validate_schedule(data.get("schedule"))
    if err:
        return None, err
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        return None, "enabled 必須是 true / false"
    return {"bot_id": bot_id, "name": name, "messages": messages, "target": target,
            "schedule": schedule, "enabled": enabled}, None


# ----------------------------------------------------------------------------
# 執行
# ----------------------------------------------------------------------------
def execute(sch: dict, kind: str) -> dict:
    """送出排程的訊息並記錄一筆執行結果。不會拋例外。"""
    db = _db()
    sent = skipped = 0
    error = None
    try:
        err = _ctx.validate_messages(sch["messages"])
        if err:
            raise ValueError(err)
        bot = db.get_bot(sch["bot_id"])
        if bot is None or not bot["enabled"]:
            raise ValueError("Bot 不存在或已停用")
        # AI 訊息：先產生一次內容，再把同樣的文字送給所有對象
        messages = ai_generate.expand(sch["messages"]) if ai_generate.has_ai(sch["messages"]) else sch["messages"]
        target = sch["target"]
        if target["type"] == "broadcast":
            user_ids = db.list_user_ids(sch["bot_id"])
        else:
            user_ids = []
            for uid in target["userIds"]:
                membership = db.get_membership(sch["bot_id"], uid)
                if membership is None or membership["blocked"]:
                    skipped += 1
                else:
                    user_ids.append(uid)
        for uid in user_ids:
            try:
                _ctx.deliver_to_client(sch["bot_id"], uid, messages)
                sent += 1
            except Exception as e:  # noqa: BLE001
                skipped += 1
                error = f"{type(e).__name__}: {str(e)[:160]}"
                logger.exception(f"排程 #{sch['id']} 無法傳給 {uid}")
    except ai_generate.AIError as e:
        error = f"AI 產生失敗：{str(e)[:200]}"
        logger.warning(f"排程 #{sch['id']} {error}")
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {str(e)[:200]}"
        logger.exception(f"排程 #{sch['id']} 執行失敗")
    db.record_run(sch["id"], kind, sent, skipped, error)
    logger.info(f"排程 #{sch['id']}「{sch['name']}」({kind}) 已執行：送出 {sent}、略過 {skipped}"
                + (f"、錯誤：{error}" if error else ""))
    return {"sent": sent, "skipped": skipped, "error": error}


def run_now(schedule_id: int):
    """手動立即執行一次（不影響原本的下次執行時間）。"""
    sch = _db().get_schedule(schedule_id)
    if sch is None:
        return None
    return execute(sch, "manual")


def process_due(now_ms=None) -> int:
    """執行所有到期的排程。回傳處理（含略過）的筆數。"""
    db = _db()
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    grace = cfg.SCHEDULE_GRACE_MINUTES * 60_000
    handled = 0
    for sch in db.due_schedules(now):
        due_at = sch["next_run_at"]
        try:
            new_next = compute_next(sch["schedule"], now)
        except Exception:  # noqa: BLE001 - 壞掉的排程資料不能卡住其他排程
            logger.exception(f"排程 #{sch['id']} 的時間設定無法計算，已停用")
            db.set_schedule_enabled(sch["id"], False, None)
            continue
        if not db.claim_schedule(sch["id"], due_at, new_next):
            continue
        handled += 1
        if now - due_at > grace:
            late_min = int((now - due_at) / 60_000)
            db.record_run(sch["id"], "missed", 0, 0, f"已逾時 {late_min} 分鐘（超過寬限時間，未補送）")
            logger.warning(f"排程 #{sch['id']}「{sch['name']}」逾時 {late_min} 分鐘，略過這一次")
        elif ai_generate.has_ai(sch["messages"]):
            # 呼叫 AI 可能要一兩分鐘，放到背景執行，不擋住其他排程
            _ctx.run_in_background(execute, sch, "auto")
        else:
            execute(sch, "auto")
    return handled
