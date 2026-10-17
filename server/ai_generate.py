"""
AI 產生訊息：排程推播執行時，先請 AI（Claude 或 OpenAI）依提示詞寫好內容，再當成文字訊息送出。

排程的 messages 裡可以放一則 LocalBot 專用的「AI 訊息」：
    {"type": "ai", "provider": "claude" | "openai", "prompt": "...",
     "model": "（可省略，用預設）", "webSearch": true, "maxChars": 1200}
執行時會換成 {"type": "text", "text": AI 的回答}，App 只會收到一般文字訊息。

API 金鑰（擇一）：
- 環境變數 LOCALBOT_ANTHROPIC_API_KEY / ANTHROPIC_API_KEY、LOCALBOT_OPENAI_API_KEY / OPENAI_API_KEY
- 後台「設定 → AI 金鑰」輸入（存在 server/.localbot_secrets.json，不會顯示完整內容）

提示詞可用變數：{today}（今天）、{yesterday}（昨天）、{weekday}（今天星期幾）、{now}（現在時間），
以伺服器時區計算，例如「請整理 {yesterday} 美股收盤…」。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta

import requests

import localconfig as cfg

logger = logging.getLogger("LocalBotPlatform")

PROVIDERS = {
    "claude": {
        "label": "Claude（Anthropic）",
        "key_name": "ANTHROPIC_API_KEY",
        "env": ("LOCALBOT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        "default_model": "claude-sonnet-5-5",
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI（ChatGPT）",
        "key_name": "OPENAI_API_KEY",
        "env": ("LOCALBOT_OPENAI_API_KEY", "OPENAI_API_KEY"),
        "default_model": "gpt-5.5",
        "key_url": "https://platform.openai.com/api-keys",
    },
}

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/responses"
REQUEST_TIMEOUT = 240  # 有網路搜尋時可能要一兩分鐘
MAX_PROMPT_CHARS = 4000
MAX_TEXT_CHARS = 5000  # 與 LINE 文字訊息上限相同
DEFAULT_MAX_CHARS = 1200
WEEKDAYS = "一二三四五六日"


class AIError(Exception):
    """給管理員看的錯誤訊息（中文）。"""


# ----------------------------------------------------------------------------
# 金鑰
# ----------------------------------------------------------------------------
def _read_file() -> dict:
    try:
        with open(cfg.SECRETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _key_and_source(provider: str):
    info = PROVIDERS[provider]
    for name in info["env"]:
        value = os.environ.get(name)
        if value:
            return value.strip(), "env"
    value = _read_file().get(info["key_name"])
    if isinstance(value, str) and value.strip():
        return value.strip(), "file"
    return None, None


def get_key(provider: str):
    return _key_and_source(provider)[0]


def key_status() -> dict:
    out = {}
    for pid, info in PROVIDERS.items():
        key, source = _key_and_source(pid)
        out[pid] = {
            "label": info["label"], "configured": bool(key), "source": source,
            "hint": f"…{key[-4:]}" if key else "", "defaultModel": info["default_model"], "keyUrl": info["key_url"],
        }
    return out


def save_key(provider: str, value):
    """儲存（value 為空 → 刪除）後台輸入的金鑰。由環境變數提供時不可改。"""
    info = PROVIDERS[provider]
    if _key_and_source(provider)[1] == "env":
        raise PermissionError("這個金鑰由環境變數設定，請改環境變數後重啟")
    data = _read_file()
    if value:
        data[info["key_name"]] = value
    else:
        data.pop(info["key_name"], None)
    cfg._write_secrets_file(data)


# ----------------------------------------------------------------------------
# 驗證 / 提示詞
# ----------------------------------------------------------------------------
def validate_ai_message(msg: dict):
    """回傳 (正規化後的 dict, 錯誤訊息)。"""
    provider = msg.get("provider")
    if provider not in PROVIDERS:
        return None, "AI 訊息的 provider 必須是 claude 或 openai"
    prompt = msg.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, "請輸入要給 AI 的指示（提示詞）"
    if len(prompt) > MAX_PROMPT_CHARS:
        return None, f"提示詞最多 {MAX_PROMPT_CHARS} 字"
    model = msg.get("model") or ""
    if not isinstance(model, str) or len(model) > 80 or any(ch.isspace() for ch in model):
        return None, "模型名稱格式錯誤"
    web = msg.get("webSearch", False)
    if not isinstance(web, bool):
        return None, "webSearch 必須是 true / false"
    max_chars = msg.get("maxChars", DEFAULT_MAX_CHARS)
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 100 <= max_chars <= MAX_TEXT_CHARS:
        return None, f"maxChars 必須是 100～{MAX_TEXT_CHARS} 的整數"
    clean = {"type": "ai", "provider": provider, "prompt": prompt.strip(), "webSearch": web, "maxChars": max_chars}
    if model:
        clean["model"] = model
    return clean, None


def render_prompt(prompt: str, now: datetime = None) -> str:
    now = now or datetime.now()
    y = now - timedelta(days=1)
    values = {
        "{today}": f"{now:%Y-%m-%d}（星期{WEEKDAYS[now.weekday()]}）",
        "{yesterday}": f"{y:%Y-%m-%d}（星期{WEEKDAYS[y.weekday()]}）",
        "{weekday}": f"星期{WEEKDAYS[now.weekday()]}",
        "{now}": f"{now:%Y-%m-%d %H:%M}",
    }
    for k, v in values.items():
        prompt = prompt.replace(k, v)
    return prompt


def system_prompt(max_chars: int, now: datetime = None) -> str:
    now = now or datetime.now()
    return (
        f"你是聊天機器人，你的回答會原封不動以一則聊天訊息傳到使用者手機。現在時間：{now:%Y-%m-%d %H:%M}"
        f"（星期{WEEKDAYS[now.weekday()]}，伺服器時區）。\n"
        "規則：使用繁體中文；只輸出要傳給使用者的內容本身，不要開場白、不要說明你做了哪些搜尋；"
        "聊天畫面不支援 Markdown，不要用 #、**、表格或程式碼區塊，可用條列符號「・」與換行、少量 emoji 讓內容好讀；"
        f"全文控制在 {max_chars} 字以內。若查不到可靠資料，直接說明查不到，不要編造數字。"
    )


def _tidy(text: str) -> str:
    text = (text or "").strip()
    # 模型偶爾仍會輸出粗體記號，聊天畫面會變成星號
    text = text.replace("**", "").replace("__", "")
    return text[:MAX_TEXT_CHARS].strip()


# ----------------------------------------------------------------------------
# 呼叫 API
# ----------------------------------------------------------------------------
def _http_error(provider: str, res) -> AIError:
    try:
        detail = res.json()
        detail = (detail.get("error") or {}).get("message") or json.dumps(detail, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        detail = (res.text or "")
    detail = " ".join(str(detail).split())[:200]
    name = PROVIDERS[provider]["label"]
    if res.status_code == 401:
        return AIError(f"{name} 的 API 金鑰無效（401），請到後台「設定」重新輸入")
    if res.status_code == 403:
        return AIError(f"{name} 拒絕這個請求（403）：{detail}")
    if res.status_code == 404:
        return AIError(f"{name} 找不到模型或功能（404），請確認模型名稱：{detail}")
    if res.status_code == 429:
        return AIError(f"{name} 用量超過限制或額度不足（429）：{detail}")
    return AIError(f"{name} 回應錯誤 HTTP {res.status_code}：{detail}")


def _post(provider: str, url: str, headers: dict, body: dict) -> dict:
    try:
        res = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        raise AIError(f"{PROVIDERS[provider]['label']} 超過 {REQUEST_TIMEOUT} 秒沒有回應") from None
    except requests.RequestException as e:
        raise AIError(f"連不上 {PROVIDERS[provider]['label']}：{type(e).__name__}") from None
    if res.status_code >= 400:
        raise _http_error(provider, res)
    try:
        return res.json()
    except ValueError:
        raise AIError("AI 回應不是 JSON") from None


def _claude(key: str, model: str, system: str, prompt: str, web: bool) -> str:
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    messages = [{"role": "user", "content": prompt}]
    body = {"model": model, "max_tokens": 4096, "system": system, "messages": messages}
    if web:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    data = {}
    for _ in range(4):  # 長時間的搜尋可能回 pause_turn，要把內容送回去讓它繼續
        data = _post("claude", ANTHROPIC_URL, headers, body)
        if data.get("stop_reason") != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": data.get("content", [])}]
        body = dict(body, messages=messages)
    blocks = data.get("content") or []
    # 只取最後一次搜尋結果之後的文字（前面常是「我來搜尋…」之類的開場）
    last_result = max((i for i, b in enumerate(blocks) if b.get("type") == "web_search_tool_result"), default=-1)
    text = "".join(b.get("text", "") for b in blocks[last_result + 1:] if b.get("type") == "text")
    if not text.strip():
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return text


def _openai(key: str, model: str, system: str, prompt: str, web: bool) -> str:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": model, "instructions": system, "input": prompt}
    if web:
        body["tools"] = [{"type": "web_search"}]
    data = _post("openai", OPENAI_URL, headers, body)
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content") or []:
            if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "\n".join(parts)


def generate(msg: dict, now: datetime = None) -> str:
    """依 AI 訊息設定產生文字。失敗時拋 AIError（訊息是給管理員看的中文）。"""
    clean, err = validate_ai_message(msg)
    if err:
        raise AIError(err)
    provider = clean["provider"]
    key = get_key(provider)
    if not key:
        raise AIError(f"還沒設定 {PROVIDERS[provider]['label']} 的 API 金鑰（後台「設定 → AI 金鑰」）")
    model = clean.get("model") or PROVIDERS[provider]["default_model"]
    now = now or datetime.now()
    system = system_prompt(clean["maxChars"], now)
    prompt = render_prompt(clean["prompt"], now)
    started = time.time()
    call = _claude if provider == "claude" else _openai
    text = _tidy(call(key, model, system, prompt, clean["webSearch"]))
    logger.info(f"AI 產生完成：{provider}/{model}，{len(text)} 字，{time.time() - started:.1f} 秒"
                + ("（含網路搜尋）" if clean["webSearch"] else ""))
    if not text:
        raise AIError("AI 沒有回傳任何文字")
    return text


def has_ai(messages) -> bool:
    return isinstance(messages, list) and any(isinstance(m, dict) and m.get("type") == "ai" for m in messages)


def expand(messages: list, now: datetime = None) -> list:
    """把 AI 訊息換成 AI 產生的文字訊息（每則只產生一次）；其他訊息原樣保留。"""
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("type") == "ai":
            out.append({"type": "text", "text": generate(m, now)})
        else:
            out.append(m)
    return out
