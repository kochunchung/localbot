"""
對應 linebot.v3.messaging 的 Configuration / ApiClient / MessagingApi / MessagingApiBlob。

與官方差異：
- host 預設讀取環境變數 LOCALBOT_SERVER_URL（未設定時為 http://localhost:5003）。
- 內容下載（MessagingApiBlob）也走同一個 host，不需另設 api-data 網域。
"""
import os
from typing import Any, Dict, Optional

import requests

from .models import (
    ErrorResponse, MessageQuotaResponse, PushMessageResponse,
    QuotaConsumptionResponse, ReplyMessageResponse, RichMenuAliasListResponse,
    RichMenuAliasResponse, RichMenuIdResponse, RichMenuListResponse, RichMenuResponse,
    UserProfileResponse,
)

DEFAULT_HOST = "http://localhost:5003"


class Configuration:
    def __init__(self, host: Optional[str] = None, access_token: Optional[str] = None, **kwargs: Any):
        self.host = (host or os.environ.get("LOCALBOT_SERVER_URL") or DEFAULT_HOST).rstrip("/")
        self.access_token = access_token
        self.timeout = kwargs.get("timeout", 10)


class ApiException(Exception):
    """與官方相同的屬性：status、reason、body、headers。"""

    def __init__(self, status=None, reason=None, http_resp=None, *, body=None, data=None):
        if http_resp is not None:
            status = http_resp.status_code
            reason = http_resp.reason
            body = http_resp.text
            self.headers = dict(http_resp.headers)
        else:
            self.headers = None
        self.status = status
        self.reason = reason
        self.body = body
        self.data = data
        super().__init__(f"({status})\nReason: {reason}\nHTTP response body: {body}")


class ApiResponse:
    def __init__(self, status_code: int, data: Any, headers: Optional[Dict[str, str]] = None, raw_data: bytes = b""):
        self.status_code = status_code
        self.data = data
        self.headers = headers or {}
        self.raw_data = raw_data


class ApiClient:
    def __init__(self, configuration: Optional[Configuration] = None):
        self.configuration = configuration or Configuration()
        self._session = requests.Session()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        self._session.close()

    def call_api(self, method: str, path: str, body: Any = None, timeout: Optional[float] = None,
                 raw: Optional[bytes] = None, content_type: Optional[str] = None) -> ApiResponse:
        cfg = self.configuration
        headers = {}
        if cfg.access_token:
            headers["Authorization"] = f"Bearer {cfg.access_token}"
        if body is not None and hasattr(body, "to_dict"):
            body = body.to_dict()
        kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout or cfg.timeout}
        if raw is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
            kwargs["data"] = bytes(raw)
        else:
            kwargs["json"] = body
        res = self._session.request(method, f"{cfg.host}{path}", **kwargs)
        if res.status_code >= 400:
            raise ApiException(http_resp=res)
        return ApiResponse(res.status_code, None, dict(res.headers), res.content)


def _json(resp: ApiResponse) -> Dict[str, Any]:
    import json
    try:
        data = json.loads(resp.raw_data or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class MessagingApi:
    def __init__(self, api_client: Optional[ApiClient] = None):
        self.api_client = api_client or ApiClient()

    def _call(self, method, path, body=None, model=None, _request_timeout=None):
        resp = self.api_client.call_api(method, path, body, _request_timeout)
        payload = _json(resp)
        resp.data = model.from_dict(payload) if model else payload
        return resp

    # ---- 訊息 ----
    def reply_message_with_http_info(self, reply_message_request, **kwargs) -> ApiResponse:
        return self._call("POST", "/v2/bot/message/reply", reply_message_request,
                          ReplyMessageResponse, kwargs.get("_request_timeout"))

    def reply_message(self, reply_message_request, **kwargs) -> ReplyMessageResponse:
        return self.reply_message_with_http_info(reply_message_request, **kwargs).data

    def push_message_with_http_info(self, push_message_request, x_line_retry_key=None, **kwargs) -> ApiResponse:
        return self._call("POST", "/v2/bot/message/push", push_message_request,
                          PushMessageResponse, kwargs.get("_request_timeout"))

    def push_message(self, push_message_request, x_line_retry_key=None, **kwargs) -> PushMessageResponse:
        return self.push_message_with_http_info(push_message_request, x_line_retry_key, **kwargs).data

    def multicast_with_http_info(self, multicast_request, x_line_retry_key=None, **kwargs) -> ApiResponse:
        return self._call("POST", "/v2/bot/message/multicast", multicast_request,
                          None, kwargs.get("_request_timeout"))

    def multicast(self, multicast_request, x_line_retry_key=None, **kwargs):
        return self.multicast_with_http_info(multicast_request, x_line_retry_key, **kwargs).data

    def broadcast_with_http_info(self, broadcast_request, x_line_retry_key=None, **kwargs) -> ApiResponse:
        return self._call("POST", "/v2/bot/message/broadcast", broadcast_request,
                          None, kwargs.get("_request_timeout"))

    def broadcast(self, broadcast_request, x_line_retry_key=None, **kwargs):
        return self.broadcast_with_http_info(broadcast_request, x_line_retry_key, **kwargs).data

    def narrowcast_with_http_info(self, narrowcast_request, x_line_retry_key=None, **kwargs) -> ApiResponse:
        return self._call("POST", "/v2/bot/message/narrowcast", narrowcast_request,
                          None, kwargs.get("_request_timeout"))

    def narrowcast(self, narrowcast_request, x_line_retry_key=None, **kwargs):
        return self.narrowcast_with_http_info(narrowcast_request, x_line_retry_key, **kwargs).data

    def show_loading_animation_with_http_info(self, show_loading_animation_request, **kwargs) -> ApiResponse:
        return self._call("POST", "/v2/bot/chat/loading/start", show_loading_animation_request,
                          None, kwargs.get("_request_timeout"))

    def show_loading_animation(self, show_loading_animation_request, **kwargs):
        return self.show_loading_animation_with_http_info(show_loading_animation_request, **kwargs).data

    # ---- 使用者 / 額度 ----
    def get_profile_with_http_info(self, user_id: str, **kwargs) -> ApiResponse:
        return self._call("GET", f"/v2/bot/profile/{user_id}", None,
                          UserProfileResponse, kwargs.get("_request_timeout"))

    def get_profile(self, user_id: str, **kwargs) -> UserProfileResponse:
        return self.get_profile_with_http_info(user_id, **kwargs).data

    def get_message_quota(self, **kwargs) -> MessageQuotaResponse:
        return self._call("GET", "/v2/bot/message/quota", None,
                          MessageQuotaResponse, kwargs.get("_request_timeout")).data

    def get_message_quota_consumption(self, **kwargs) -> QuotaConsumptionResponse:
        return self._call("GET", "/v2/bot/message/quota/consumption", None,
                          QuotaConsumptionResponse, kwargs.get("_request_timeout")).data

    # ---- Rich Menu（方法名稱與官方 v3 相同）----
    def create_rich_menu(self, rich_menu_request, **kwargs) -> RichMenuIdResponse:
        return self._call("POST", "/v2/bot/richmenu", rich_menu_request,
                          RichMenuIdResponse, kwargs.get("_request_timeout")).data

    def validate_rich_menu_object(self, rich_menu_request, **kwargs):
        return self._call("POST", "/v2/bot/richmenu/validate", rich_menu_request,
                          None, kwargs.get("_request_timeout")).data

    def get_rich_menu(self, rich_menu_id: str, **kwargs) -> RichMenuResponse:
        return self._call("GET", f"/v2/bot/richmenu/{rich_menu_id}", None,
                          RichMenuResponse, kwargs.get("_request_timeout")).data

    def get_rich_menu_list(self, **kwargs) -> RichMenuListResponse:
        return self._call("GET", "/v2/bot/richmenu/list", None,
                          RichMenuListResponse, kwargs.get("_request_timeout")).data

    def delete_rich_menu(self, rich_menu_id: str, **kwargs):
        return self._call("DELETE", f"/v2/bot/richmenu/{rich_menu_id}", None,
                          None, kwargs.get("_request_timeout")).data

    def set_default_rich_menu(self, rich_menu_id: str, **kwargs):
        return self._call("POST", f"/v2/bot/user/all/richmenu/{rich_menu_id}", None,
                          None, kwargs.get("_request_timeout")).data

    def get_default_rich_menu_id(self, **kwargs) -> RichMenuIdResponse:
        return self._call("GET", "/v2/bot/user/all/richmenu", None,
                          RichMenuIdResponse, kwargs.get("_request_timeout")).data

    def cancel_default_rich_menu(self, **kwargs):
        return self._call("DELETE", "/v2/bot/user/all/richmenu", None,
                          None, kwargs.get("_request_timeout")).data

    def link_rich_menu_id_to_user(self, user_id: str, rich_menu_id: str, **kwargs):
        return self._call("POST", f"/v2/bot/user/{user_id}/richmenu/{rich_menu_id}", None,
                          None, kwargs.get("_request_timeout")).data

    def link_rich_menu_id_to_users(self, rich_menu_bulk_link_request, **kwargs):
        return self._call("POST", "/v2/bot/richmenu/bulk/link", rich_menu_bulk_link_request,
                          None, kwargs.get("_request_timeout")).data

    def unlink_rich_menu_id_from_user(self, user_id: str, **kwargs):
        return self._call("DELETE", f"/v2/bot/user/{user_id}/richmenu", None,
                          None, kwargs.get("_request_timeout")).data

    def unlink_rich_menu_id_from_users(self, rich_menu_bulk_unlink_request, **kwargs):
        return self._call("POST", "/v2/bot/richmenu/bulk/unlink", rich_menu_bulk_unlink_request,
                          None, kwargs.get("_request_timeout")).data

    def get_rich_menu_id_of_user(self, user_id: str, **kwargs) -> RichMenuIdResponse:
        return self._call("GET", f"/v2/bot/user/{user_id}/richmenu", None,
                          RichMenuIdResponse, kwargs.get("_request_timeout")).data

    def create_rich_menu_alias(self, create_rich_menu_alias_request, **kwargs):
        return self._call("POST", "/v2/bot/richmenu/alias", create_rich_menu_alias_request,
                          None, kwargs.get("_request_timeout")).data

    def update_rich_menu_alias(self, rich_menu_alias_id: str, update_rich_menu_alias_request, **kwargs):
        return self._call("POST", f"/v2/bot/richmenu/alias/{rich_menu_alias_id}", update_rich_menu_alias_request,
                          None, kwargs.get("_request_timeout")).data

    def delete_rich_menu_alias(self, rich_menu_alias_id: str, **kwargs):
        return self._call("DELETE", f"/v2/bot/richmenu/alias/{rich_menu_alias_id}", None,
                          None, kwargs.get("_request_timeout")).data

    def get_rich_menu_alias(self, rich_menu_alias_id: str, **kwargs) -> RichMenuAliasResponse:
        return self._call("GET", f"/v2/bot/richmenu/alias/{rich_menu_alias_id}", None,
                          RichMenuAliasResponse, kwargs.get("_request_timeout")).data

    def get_rich_menu_alias_list(self, **kwargs) -> RichMenuAliasListResponse:
        return self._call("GET", "/v2/bot/richmenu/alias/list", None,
                          RichMenuAliasListResponse, kwargs.get("_request_timeout")).data


class MessagingApiBlob:
    def __init__(self, api_client: Optional[ApiClient] = None):
        self.api_client = api_client or ApiClient()

    def get_message_content_with_http_info(self, message_id: str, **kwargs) -> ApiResponse:
        resp = self.api_client.call_api("GET", f"/v2/bot/message/{message_id}/content",
                                        None, kwargs.get("_request_timeout"))
        resp.data = bytearray(resp.raw_data)
        return resp

    def get_message_content(self, message_id: str, **kwargs) -> bytearray:
        return self.get_message_content_with_http_info(message_id, **kwargs).data

    def set_rich_menu_image(self, rich_menu_id: str, body, _headers: Optional[Dict[str, str]] = None, **kwargs):
        """上傳 Rich Menu 圖片（PNG / JPEG，最大 1 MB）。
        與官方相同可用 _headers={'Content-Type': 'image/png'}；未指定時依檔頭自動判斷。"""
        data = body.read() if hasattr(body, "read") else bytes(body)
        content_type = (_headers or {}).get("Content-Type") or kwargs.get("content_type")
        if not content_type:
            content_type = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        resp = self.api_client.call_api("POST", f"/v2/bot/richmenu/{rich_menu_id}/content", None,
                                        kwargs.get("_request_timeout"), raw=data, content_type=content_type)
        return _json(resp)

    def get_rich_menu_image(self, rich_menu_id: str, **kwargs) -> bytearray:
        resp = self.api_client.call_api("GET", f"/v2/bot/richmenu/{rich_menu_id}/content",
                                        None, kwargs.get("_request_timeout"))
        return bytearray(resp.raw_data)


__all__ = [
    "Configuration", "ApiClient", "ApiException", "ApiResponse",
    "MessagingApi", "MessagingApiBlob", "ErrorResponse",
]
