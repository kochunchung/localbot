"""管理後台：排程推播與 Webhook 轉送日誌的 API（掛在 admin_panel 的 blueprint 上）。"""
import time
from datetime import datetime

from flask import jsonify, request

import ai_generate
import scheduled_push
import webhook_delivery
from admin_panel import _audit, _bot_filter, _bot_names, _err, _int_arg, _json, admin_required, bp, c


def utc_offset_minutes() -> int:
    off = datetime.now().astimezone().utcoffset()
    return int(off.total_seconds() // 60) if off else 0


# ============================================================================
# 排程推播
# ============================================================================
def _schedule_view(row: dict, names=None) -> dict:
    names = names if names is not None else _bot_names()
    if not row["enabled"]:
        status = "paused"
    elif row["next_run_at"] is None:
        status = "done"
    else:
        status = "active"
    return {
        "id": row["id"], "botId": row["bot_id"], "botName": names.get(row["bot_id"]),
        "name": row["name"], "messages": row["messages"], "target": row["target"],
        "schedule": row["schedule"], "enabled": row["enabled"], "status": status,
        "nextRunAt": row["next_run_at"], "lastRunAt": row["last_run_at"], "lastResult": row["last_result"],
        "runCount": row["run_count"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def _get_or_404(schedule_id: int):
    row = c().db.get_schedule(schedule_id)
    if row is None:
        return None, _err("找不到這個排程", 404)
    return row, None


def _next_for_save(fields: dict):
    """回傳 (next_run_at, 錯誤回應)。停用中的排程不排時間。"""
    if not fields["enabled"]:
        return None, None
    nxt = scheduled_push.compute_next(fields["schedule"], int(time.time() * 1000))
    if nxt is None:
        return None, _err("單次排程的時間已經過了，請選擇未來的時間")
    return nxt, None


@bp.get("/api/schedules")
@admin_required
def schedules_list():
    bot_id, err = _bot_filter()
    if err:
        return err
    names = _bot_names()
    rows = c().db.list_schedules(bot_id)
    return jsonify({"schedules": [_schedule_view(r, names) for r in rows],
                    "serverTime": int(time.time() * 1000), "utcOffsetMinutes": utc_offset_minutes()})


@bp.post("/api/schedules/preview")
@admin_required
def schedule_preview():
    schedule, err = scheduled_push.validate_schedule(_json().get("schedule"))
    if err:
        return _err(err)
    return jsonify({"next": scheduled_push.preview(schedule, 3)})


@bp.post("/api/schedules")
@admin_required
def schedule_create():
    fields, err = scheduled_push.validate_payload(_json())
    if err:
        return _err(err)
    nxt, bad = _next_for_save(fields)
    if bad:
        return bad
    sid = c().db.create_schedule(fields["bot_id"], fields["name"], fields["messages"], fields["target"], fields["schedule"],
                                 fields["enabled"], nxt)
    _audit("schedule.create", id=sid, bot=fields["bot_id"], kind=fields["schedule"]["type"], target=fields["target"]["type"])
    return jsonify(_schedule_view(c().db.get_schedule(sid))), 201


@bp.get("/api/schedules/<int:schedule_id>")
@admin_required
def schedule_get(schedule_id):
    row, err = _get_or_404(schedule_id)
    return err or jsonify(_schedule_view(row))


@bp.put("/api/schedules/<int:schedule_id>")
@admin_required
def schedule_update(schedule_id):
    row, err = _get_or_404(schedule_id)
    if err:
        return err
    fields, msg = scheduled_push.validate_payload(_json())
    if msg:
        return _err(msg)
    if (row["schedule"] == fields["schedule"] and row["enabled"] == fields["enabled"]
            and (row["next_run_at"] is not None or not fields["enabled"])):
        nxt = row["next_run_at"]  # 時間設定沒變：保留原本的下次執行時間
    else:
        nxt, bad = _next_for_save(fields)
        if bad:
            return bad
    c().db.update_schedule(schedule_id, fields["bot_id"], fields["name"], fields["messages"], fields["target"], fields["schedule"],
                           fields["enabled"], nxt)
    _audit("schedule.update", id=schedule_id)
    return jsonify(_schedule_view(c().db.get_schedule(schedule_id)))


@bp.patch("/api/schedules/<int:schedule_id>")
@admin_required
def schedule_toggle(schedule_id):
    row, err = _get_or_404(schedule_id)
    if err:
        return err
    enabled = _json().get("enabled")
    if not isinstance(enabled, bool):
        return _err("enabled 必須是 true / false")
    nxt, bad = _next_for_save({"enabled": enabled, "schedule": row["schedule"]})
    if bad:
        return bad
    c().db.set_schedule_enabled(schedule_id, enabled, nxt)
    _audit("schedule.toggle", id=schedule_id, enabled=enabled)
    return jsonify(_schedule_view(c().db.get_schedule(schedule_id)))


@bp.delete("/api/schedules/<int:schedule_id>")
@admin_required
def schedule_delete(schedule_id):
    if not c().db.delete_schedule(schedule_id):
        return _err("找不到這個排程", 404)
    _audit("schedule.delete", id=schedule_id)
    return jsonify({"deleted": True})


@bp.post("/api/schedules/<int:schedule_id>/run")
@admin_required
def schedule_run(schedule_id):
    row, err = _get_or_404(schedule_id)
    if err:
        return err
    if _json().get("confirm") is not True:
        return _err("立即執行需要 confirm: true")
    result = scheduled_push.run_now(schedule_id)
    _audit("schedule.run", id=schedule_id, sent=result["sent"], skipped=result["skipped"])
    return jsonify(result)


@bp.get("/api/schedules/<int:schedule_id>/runs")
@admin_required
def schedule_runs(schedule_id):
    _, err = _get_or_404(schedule_id)
    if err:
        return err
    return jsonify({"runs": c().db.list_runs(schedule_id)})


# ============================================================================
# AI 產生訊息（排程推播用）：金鑰設定與試產生
# ============================================================================
@bp.get("/api/ai")
@admin_required
def ai_status():
    return jsonify({"providers": ai_generate.key_status(),
                    "variables": ["{today}", "{yesterday}", "{weekday}", "{now}"]})


@bp.put("/api/ai/keys/<provider>")
@admin_required
def ai_key_save(provider):
    if provider not in ai_generate.PROVIDERS:
        return _err("未知的 AI 服務", 404)
    value = _json().get("key")
    if value is None:
        value = ""
    if not isinstance(value, str):
        return _err("金鑰格式錯誤")
    value = value.strip()
    if value and (len(value) < 20 or len(value) > 300 or any(ch.isspace() for ch in value)):
        return _err("金鑰格式看起來不對，請重新複製")
    try:
        ai_generate.save_key(provider, value)
    except PermissionError as e:
        return _err(str(e), 409)
    _audit("ai.key." + ("set" if value else "clear"), provider=provider)
    return jsonify({"providers": ai_generate.key_status()})


@bp.post("/api/ai/preview")
@admin_required
def ai_preview():
    """試產生一次（不會傳給任何人），讓管理員調整提示詞。"""
    data = _json()
    msg = {k: data.get(k) for k in ("provider", "prompt", "model", "webSearch", "maxChars") if k in data}
    started = time.time()
    try:
        text = ai_generate.generate(msg)
    except ai_generate.AIError as e:
        return _err(str(e), 502)
    _audit("ai.preview", provider=msg.get("provider"))
    return jsonify({"text": text, "ms": int((time.time() - started) * 1000)})


# ============================================================================
# Webhook 轉送日誌
# ============================================================================
def _delivery_view(row: dict, names=None) -> dict:
    names = names if names is not None else _bot_names()
    return {
        "id": row["id"], "botId": row["bot_id"], "botName": names.get(row["bot_id"]), "userId": row["user_id"], "eventType": row["event_type"], "eventId": row["event_id"],
        "eventCount": row["event_count"], "state": row["state"], "attempts": row["attempts"],
        "lastStatus": row["last_status"], "lastError": row["last_error"], "nextAttemptAt": row["next_attempt_at"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


@bp.get("/api/webhook/deliveries")
@admin_required
def deliveries_list():
    state = request.args.get("state") or None
    q = (request.args.get("q") or "").strip()[:100] or None
    before = _int_arg("beforeId", 0, 0, 2 ** 62) or None
    bot_id, err = _bot_filter()
    if err:
        return err
    result = c().db.list_deliveries(state=state, q=q, limit=_int_arg("limit", 50, 1, 200), before_id=before,
                                    bot_id=bot_id)
    names = _bot_names()
    return jsonify({"deliveries": [_delivery_view(r, names) for r in result["deliveries"]],
                    "hasMore": result["hasMore"], "counts": c().db.delivery_counts(bot_id)})


@bp.get("/api/webhook/deliveries/<int:delivery_id>")
@admin_required
def delivery_get(delivery_id):
    row = c().db.get_delivery(delivery_id)
    if row is None:
        return _err("找不到這筆紀錄", 404)
    view = _delivery_view(row)
    view["body"] = row["body"]
    view["attemptLog"] = [
        {"no": a["attempt_no"], "manual": bool(a["manual"]), "ok": bool(a["ok"]), "status": a["status_code"],
         "error": a["error"], "ms": a["duration_ms"], "at": a["created_at"]}
        for a in c().db.list_attempts(delivery_id)]
    return jsonify(view)


@bp.post("/api/webhook/deliveries/resend-failed")
@admin_required
def deliveries_resend_failed():
    if _json().get("confirm") is not True:
        return _err("需要 confirm: true")
    n = webhook_delivery.resend_all_dead()
    _audit("webhook.resend_failed", count=n)
    return jsonify({"queued": n})


@bp.post("/api/webhook/deliveries/<int:delivery_id>/resend")
@admin_required
def delivery_resend(delivery_id):
    result, code = webhook_delivery.resend(delivery_id)
    if code == "not_found":
        return _err("找不到這筆紀錄", 404)
    if code == "busy":
        return _err("這筆正在轉送中，請稍後再試", 409)
    _audit("webhook.resend", id=delivery_id, ok=result["ok"])
    return jsonify({"ok": result["ok"], "status": result["status"], "error": result["error"],
                    "state": result["state"], "ms": result["ms"]})
