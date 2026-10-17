"""
Webhook 轉送：紀錄每一次對 Bot 的轉送、失敗自動重試、後台手動重送。

狀態（存在資料庫，重啟後仍會繼續）：
  sending  → 正在嘗試
  success  → Bot 回 2xx/3xx
  retrying → 失敗，等到 next_attempt_at 再試（遞增間隔，見 LOCALBOT_WEBHOOK_RETRY_DELAYS）
  dead     → 放棄（重試用完、Bot 回不可重試的 4xx、或手動重送失敗），可在後台手動重送

重送的事件會帶 deliveryContext.isRedelivery = true，webhookEventId 維持不變，
Bot 可以用它去重（和 LINE 平台的行為一致）。
"""
import json
import logging
import threading
import time
import uuid

import localconfig as cfg
from localbot.utils import calculate_signature

logger = logging.getLogger("LocalBotPlatform")

# app.forward_to_bot 在這裡留下失敗原因（thread-local，避免改它的回傳值）
forward_state = threading.local()

RETRYABLE_STATUS = {408, 425, 429}

_ctx = None


def init(ctx):
    """ctx 是 app 模組（db、forward_to_bot、CHANNEL_SECRET 都在呼叫時才查，測試才能替換）。"""
    global _ctx
    _ctx = ctx


def _db():
    return _ctx.db


def is_retryable(status, error) -> bool:
    if error:  # 連線失敗 / 逾時
        return True
    return status in RETRYABLE_STATUS or (status is not None and status >= 500)


def _events(body: str):
    try:
        payload = json.loads(body)
    except Exception:
        return None, []
    events = payload.get("events") if isinstance(payload, dict) else None
    return payload, events if isinstance(events, list) else []


def with_event_ids(body: str) -> str:
    """確保每個事件都有 webhookEventId / deliveryContext；沒有需要補的就原字串回傳。"""
    payload, events = _events(body)
    changed = False
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if "webhookEventId" not in ev:
            ev["webhookEventId"] = uuid.uuid4().hex.upper()
            changed = True
        if "deliveryContext" not in ev:
            ev["deliveryContext"] = {"isRedelivery": False}
            changed = True
    return json.dumps(payload, ensure_ascii=False) if changed else body


def as_redelivery(body: str) -> str:
    payload, events = _events(body)
    for ev in events:
        if isinstance(ev, dict):
            ev["deliveryContext"] = {"isRedelivery": True}
    return json.dumps(payload, ensure_ascii=False) if events else body


def _summary(body: str):
    _, events = _events(body)
    first = next((e for e in events if isinstance(e, dict)), {})
    source = first.get("source") if isinstance(first.get("source"), dict) else {}
    return (source.get("userId"), first.get("type"), first.get("webhookEventId"), len(events))


def _plain_error(err: str, status, snippet) -> str:
    if err:
        return err[:300]
    text = f"HTTP {status}"
    if snippet:
        text += f"：{snippet}"
    return text[:300]


def _attempt(delivery_id: int, manual=None) -> dict:
    """對一筆已搶占（state=sending）的轉送做一次嘗試，並依結果更新狀態。"""
    db = _db()
    row = db.get_delivery(delivery_id)
    if row is None:
        return {"id": delivery_id, "ok": False, "state": "missing"}
    if manual is None:
        manual = bool(row.get("manual_pending"))
    body = as_redelivery(row["body"]) if row["attempts"] > 0 else row["body"]
    bot = db.get_bot(row["bot_id"])

    forward_state.error = None
    forward_state.snippet = None
    started = time.time()
    status = None
    if bot is None or not bot["enabled"]:
        # Bot 已刪除或停用：不重試，等管理員處理後在後台手動重送
        db.record_attempt(delivery_id, False, None, "Bot 不存在或已停用", 0, bool(manual), "dead", None)
        return {"id": delivery_id, "ok": False, "status": None, "error": "Bot 不存在或已停用",
                "state": "dead", "retryAt": None, "ms": 0}
    try:
        signature = calculate_signature(bot["channel_secret"], body)
        status = _ctx.forward_to_bot(bot, body, signature)
        status = int(status)
    except Exception as e:  # noqa: BLE001
        forward_state.error = forward_state.error or f"{type(e).__name__}: {e}"
        status = None
    error = getattr(forward_state, "error", None)
    snippet = getattr(forward_state, "snippet", None)
    duration = int((time.time() - started) * 1000)
    if error:
        status = None  # 沒有收到 HTTP 回應（forward_to_bot 對例外回傳 500，不是真的狀態碼）

    ok = error is None and status is not None and status < 400
    now = int(time.time() * 1000)
    retry_at = None
    if ok:
        state = "success"
        message = None
    else:
        message = _plain_error(error, status, snippet)
        state = "dead"
        if not manual and is_retryable(status, error):
            done = db.count_auto_attempts(delivery_id)  # 這次之前的自動嘗試次數
            delays = cfg.WEBHOOK_RETRY_DELAYS
            if done < len(delays):  # 第 1 次失敗 → delays[0]，第 2 次 → delays[1] …
                state = "retrying"
                retry_at = now + int(delays[done] * 1000)
    db.record_attempt(delivery_id, ok, status, message, duration, bool(manual), state, retry_at)
    if ok:
        logger.info(f"Webhook delivery #{delivery_id} ok (status={status}, {duration}ms, manual={manual})")
    else:
        logger.warning(f"Webhook delivery #{delivery_id} failed: {message} → {state}"
                       + (f" (retry in {int((retry_at - now) / 1000)}s)" if retry_at else ""))
    return {"id": delivery_id, "ok": ok, "status": status, "error": message, "state": state,
            "retryAt": retry_at, "ms": duration}


def deliver(bot_id: str, body: str) -> dict:
    """第一次轉送給指定 Bot（同步）。失敗且可重試時排入重試佇列，不拋例外。"""
    try:
        body = with_event_ids(body)
        user_id, event_type, event_id, count = _summary(body)
        delivery_id = _db().create_delivery(bot_id, user_id, event_type, event_id, body, count)
    except Exception:  # noqa: BLE001 - 紀錄失敗不能擋住轉送
        logger.exception("無法建立 webhook 轉送紀錄，直接轉送")
        bot = _db().get_bot(bot_id)
        if bot is None:
            return {"id": None, "ok": False, "status": None, "state": "dead"}
        status = _ctx.forward_to_bot(bot, body, calculate_signature(bot["channel_secret"], body))
        return {"id": None, "ok": status < 400, "status": status, "state": "success" if status < 400 else "dead"}
    return _attempt(delivery_id, manual=False)


def deliver_safe(bot_id: str, body: str):
    """給背景執行緒用：例外只記 log。"""
    try:
        deliver(bot_id, body)
    except Exception:  # noqa: BLE001
        logger.exception("webhook 轉送失敗")


def process_due(now_ms=None, limit: int = 5) -> int:
    """處理到期的重試。回傳實際嘗試的筆數。"""
    db = _db()
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    done = 0
    for delivery_id in db.due_deliveries(now, limit):
        if not db.claim_delivery(delivery_id, now):
            continue
        try:
            _attempt(delivery_id)
        except Exception:  # noqa: BLE001
            logger.exception(f"重試 #{delivery_id} 發生錯誤，稍後再試")
            db.record_attempt(delivery_id, False, None, "內部錯誤", 0, False, "retrying", now + 60_000)
        done += 1
    return done


def resend(delivery_id: int):
    """後台手動重送（立刻同步執行一次）。回傳 (結果 dict | None, 錯誤代碼 | None)。"""
    db = _db()
    row = db.get_delivery(delivery_id)
    if row is None:
        return None, "not_found"
    if not db.claim_delivery(delivery_id, only_due=False):
        return None, "busy"
    return _attempt(delivery_id, manual=True), None


def resend_all_dead(limit: int = 100) -> int:
    """把所有放棄的轉送排回佇列，由背景工作逐一重送。"""
    return _db().requeue_dead(limit=limit)
