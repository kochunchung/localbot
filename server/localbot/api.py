"""
LineBotApi implementation for localbot SDK.
"""
from typing import Any, Dict, Generator, List, Optional, Union
import os
import io
import json
from .models import SendMessage
from .exceptions import LineBotApiError


class MessageContent:
    """Represents binary content returned by get_message_content."""
    def __init__(self, data: bytes):
        self._data = data

    @property
    def content(self) -> bytes:
        return self._data

    def iter_content(self, chunk_size: int = 1024) -> Generator[bytes, None, None]:
        stream = io.BytesIO(self._data)
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            yield chunk


class LineBotApi:
    def __init__(
        self,
        channel_access_token: str,
        server_url: Optional[str] = None,
        media_dir: Optional[str] = None,
    ):
        self.channel_access_token = channel_access_token
        self.server_url = server_url
        self.media_dir = media_dir or os.path.join(os.getcwd(), "media")
        self._bridge: Optional[Any] = None

    def set_bridge(self, bridge: Any):
        """Set in-process bridge for communicating with SocketIO & database."""
        self._bridge = bridge

    def reply_message(
        self,
        reply_token: str,
        messages: Union[SendMessage, List[SendMessage]],
        notification_disabled: bool = False,
    ):
        """Reply to a message using reply_token, matching linebot.LineBotApi.reply_message."""
        msg_list = messages if isinstance(messages, list) else [messages]
        serialized_messages = [
            m.as_json_dict() if hasattr(m, 'as_json_dict') else m
            for m in msg_list
        ]

        if self._bridge is not None:
            return self._bridge.reply_message(reply_token, serialized_messages)

        # Out-of-process fallback via HTTP if server_url configured
        if self.server_url:
            import requests
            headers = {"Authorization": f"Bearer {self.channel_access_token}"}
            res = requests.post(
                f"{self.server_url.rstrip('/')}/api/v1/bot/reply",
                headers=headers,
                json={"replyToken": reply_token, "messages": serialized_messages},
                timeout=10,
            )
            if res.status_code != 200:
                raise LineBotApiError(status_code=res.status_code, error=res.text)
            return res.json()

        raise RuntimeError("LineBotApi has neither internal bridge nor server_url configured.")

    def push_message(
        self,
        to: str,
        messages: Union[SendMessage, List[SendMessage]],
        notification_disabled: bool = False,
    ):
        """Push a message to a user ID, matching linebot.LineBotApi.push_message."""
        msg_list = messages if isinstance(messages, list) else [messages]
        serialized_messages = [
            m.as_json_dict() if hasattr(m, 'as_json_dict') else m
            for m in msg_list
        ]

        if self._bridge is not None:
            return self._bridge.push_message(to, serialized_messages)

        # Out-of-process fallback via HTTP if server_url configured
        if self.server_url:
            import requests
            headers = {"Authorization": f"Bearer {self.channel_access_token}"}
            res = requests.post(
                f"{self.server_url.rstrip('/')}/api/v1/bot/push",
                headers=headers,
                json={"to": to, "messages": serialized_messages},
                timeout=10,
            )
            if res.status_code != 200:
                raise LineBotApiError(status_code=res.status_code, error=res.text)
            return res.json()

        raise RuntimeError("LineBotApi has neither internal bridge nor server_url configured.")

    # ------------------------------------------------------------------
    # 多人推播 / 額度（對應 LINE /v2/bot/message/* 端點）
    # ------------------------------------------------------------------
    @staticmethod
    def _serialize(messages) -> list:
        msg_list = messages if isinstance(messages, list) else [messages]
        return [m.as_json_dict() if hasattr(m, 'as_json_dict') else m for m in msg_list]

    def _v2_request(self, method: str, path: str, payload: Optional[dict] = None, timeout: int = 10):
        if not self.server_url:
            raise RuntimeError("此功能需要設定 server_url。")
        import requests
        headers = {"Authorization": f"Bearer {self.channel_access_token}"}
        res = requests.request(
            method,
            f"{self.server_url.rstrip('/')}{path}",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if res.status_code >= 400:
            raise LineBotApiError(status_code=res.status_code, error=res.text)
        try:
            return res.json()
        except ValueError:
            return {}

    def multicast(self, to: List[str], messages, notification_disabled: bool = False, timeout=None):
        """一次推播給多位使用者（最多 500 人）。"""
        serialized = self._serialize(messages)
        if self._bridge is not None and not self.server_url:
            for uid in dict.fromkeys(to):
                self._bridge.push_message(uid, serialized)
            return {}
        return self._v2_request("POST", "/v2/bot/message/multicast",
                                {"to": list(to), "messages": serialized}, timeout or 10)

    def broadcast(self, messages, notification_disabled: bool = False, timeout=None):
        """推播給所有已註冊的使用者。"""
        return self._v2_request("POST", "/v2/bot/message/broadcast",
                                {"messages": self._serialize(messages)}, timeout or 10)

    def narrowcast(self, messages, recipient=None, filter=None, limit=None, timeout=None):
        """LocalBot 尚無受眾資料，narrowcast 會視同 broadcast。"""
        payload = {"messages": self._serialize(messages)}
        if recipient is not None:
            payload["recipient"] = recipient
        if filter is not None:
            payload["filter"] = filter
        return self._v2_request("POST", "/v2/bot/message/narrowcast", payload, timeout or 10)

    def get_message_quota(self, timeout=None):
        from .models import MessageQuota
        data = self._v2_request("GET", "/v2/bot/message/quota", timeout=timeout or 10)
        return MessageQuota(type=data.get("type", "none"), value=data.get("value"))

    def get_message_quota_consumption(self, timeout=None):
        from .models import QuotaConsumption
        data = self._v2_request("GET", "/v2/bot/message/quota/consumption", timeout=timeout or 10)
        return QuotaConsumption(total_usage=data.get("totalUsage", 0))

    def show_loading_animation(self, chat_id: str, loading_seconds: int = 20, timeout=None):
        """在 App 顯示「輸入中」動畫（loading_seconds：5～60，5 的倍數）。"""
        return self._v2_request("POST", "/v2/bot/chat/loading/start",
                                {"chatId": chat_id, "loadingSeconds": loading_seconds}, timeout or 10)

    # ------------------------------------------------------------------
    # Rich Menu（方法名稱與官方 v1 SDK 相同）
    # ------------------------------------------------------------------
    def create_rich_menu(self, rich_menu, timeout=None) -> str:
        body = rich_menu.as_json_dict() if hasattr(rich_menu, "as_json_dict") else rich_menu
        return self._v2_request("POST", "/v2/bot/richmenu", body, timeout or 10)["richMenuId"]

    def validate_rich_menu_object(self, rich_menu, timeout=None):
        body = rich_menu.as_json_dict() if hasattr(rich_menu, "as_json_dict") else rich_menu
        return self._v2_request("POST", "/v2/bot/richmenu/validate", body, timeout or 10)

    def get_rich_menu(self, rich_menu_id: str, timeout=None):
        from .models import RichMenuResponse
        return RichMenuResponse.from_dict(self._v2_request("GET", f"/v2/bot/richmenu/{rich_menu_id}", timeout=timeout or 10))

    def get_rich_menu_list(self, timeout=None):
        from .models import RichMenuResponse
        data = self._v2_request("GET", "/v2/bot/richmenu/list", timeout=timeout or 10)
        return [RichMenuResponse.from_dict(m) for m in data.get("richmenus", [])]

    def delete_rich_menu(self, rich_menu_id: str, timeout=None):
        return self._v2_request("DELETE", f"/v2/bot/richmenu/{rich_menu_id}", timeout=timeout or 10)

    def set_rich_menu_image(self, rich_menu_id: str, content_type: str, content, timeout=None):
        """content 可以是 bytes 或已開啟的檔案。"""
        if not self.server_url:
            raise RuntimeError("此功能需要設定 server_url。")
        import requests
        data = content.read() if hasattr(content, "read") else content
        res = requests.post(
            f"{self.server_url.rstrip('/')}/v2/bot/richmenu/{rich_menu_id}/content",
            headers={"Authorization": f"Bearer {self.channel_access_token}", "Content-Type": content_type},
            data=data,
            timeout=timeout or 30,
        )
        if res.status_code >= 400:
            raise LineBotApiError(status_code=res.status_code, error=res.text)
        return {}

    def get_rich_menu_image(self, rich_menu_id: str, timeout=None) -> "MessageContent":
        if not self.server_url:
            raise RuntimeError("此功能需要設定 server_url。")
        import requests
        res = requests.get(
            f"{self.server_url.rstrip('/')}/v2/bot/richmenu/{rich_menu_id}/content",
            headers={"Authorization": f"Bearer {self.channel_access_token}"},
            timeout=timeout or 30,
        )
        if res.status_code >= 400:
            raise LineBotApiError(status_code=res.status_code, error=res.text)
        return MessageContent(res.content)

    def link_rich_menu_to_user(self, user_id: str, rich_menu_id: str, timeout=None):
        return self._v2_request("POST", f"/v2/bot/user/{user_id}/richmenu/{rich_menu_id}", timeout=timeout or 10)

    def link_rich_menu_to_users(self, user_ids: List[str], rich_menu_id: str, timeout=None):
        return self._v2_request("POST", "/v2/bot/richmenu/bulk/link",
                                {"richMenuId": rich_menu_id, "userIds": list(user_ids)}, timeout or 10)

    def unlink_rich_menu_from_user(self, user_id: str, timeout=None):
        return self._v2_request("DELETE", f"/v2/bot/user/{user_id}/richmenu", timeout=timeout or 10)

    def unlink_rich_menu_from_users(self, user_ids: List[str], timeout=None):
        return self._v2_request("POST", "/v2/bot/richmenu/bulk/unlink", {"userIds": list(user_ids)}, timeout or 10)

    def get_rich_menu_id_of_user(self, user_id: str, timeout=None) -> str:
        return self._v2_request("GET", f"/v2/bot/user/{user_id}/richmenu", timeout=timeout or 10)["richMenuId"]

    def set_default_rich_menu(self, rich_menu_id: str, timeout=None):
        return self._v2_request("POST", f"/v2/bot/user/all/richmenu/{rich_menu_id}", timeout=timeout or 10)

    def get_default_rich_menu_id(self, timeout=None) -> str:
        return self._v2_request("GET", "/v2/bot/user/all/richmenu", timeout=timeout or 10)["richMenuId"]

    def cancel_default_rich_menu(self, timeout=None):
        return self._v2_request("DELETE", "/v2/bot/user/all/richmenu", timeout=timeout or 10)

    def create_rich_menu_alias(self, rich_menu_alias, timeout=None):
        return self._v2_request("POST", "/v2/bot/richmenu/alias", rich_menu_alias.as_json_dict(), timeout or 10)

    def update_rich_menu_alias(self, rich_menu_alias_id: str, rich_menu_alias, timeout=None):
        return self._v2_request("POST", f"/v2/bot/richmenu/alias/{rich_menu_alias_id}",
                                {"richMenuId": rich_menu_alias.richMenuId}, timeout or 10)

    def delete_rich_menu_alias(self, rich_menu_alias_id: str, timeout=None):
        return self._v2_request("DELETE", f"/v2/bot/richmenu/alias/{rich_menu_alias_id}", timeout=timeout or 10)

    def get_rich_menu_alias(self, rich_menu_alias_id: str, timeout=None):
        from .models import RichMenuAlias
        data = self._v2_request("GET", f"/v2/bot/richmenu/alias/{rich_menu_alias_id}", timeout=timeout or 10)
        return RichMenuAlias(data["richMenuAliasId"], data["richMenuId"])

    def get_rich_menu_alias_list(self, timeout=None):
        from .models import RichMenuAlias
        data = self._v2_request("GET", "/v2/bot/richmenu/alias/list", timeout=timeout or 10)
        return [RichMenuAlias(a["richMenuAliasId"], a["richMenuId"]) for a in data.get("aliases", [])]

    def get_message_content(self, message_id: str) -> MessageContent:
        """Retrieve binary content (image/audio/video) for a given message ID."""
        if self._bridge is not None and hasattr(self._bridge, 'get_message_content'):
            data = self._bridge.get_message_content(message_id)
            if data is not None:
                return MessageContent(data)

        # Check local media directory
        if os.path.exists(self.media_dir):
            for fname in os.listdir(self.media_dir):
                if fname.startswith(f"{message_id}."):
                    fpath = os.path.join(self.media_dir, fname)
                    with open(fpath, 'rb') as f:
                        return MessageContent(f.read())

        # If not found locally and server_url is configured, fetch via HTTP
        if self.server_url:
            import requests
            headers = {"Authorization": f"Bearer {self.channel_access_token}"}
            res = requests.get(
                f"{self.server_url.rstrip('/')}/api/v1/bot/content/{message_id}",
                headers=headers,
                timeout=15,
            )
            if res.status_code == 200:
                return MessageContent(res.content)
            raise LineBotApiError(status_code=res.status_code, error=res.text)

        raise FileNotFoundError(f"Media content for message_id '{message_id}' not found.")

    def get_profile(self, user_id: str, timeout: Optional[int] = None) -> Any:
        """Get user profile matching linebot.LineBotApi.get_profile."""
        from .models import Profile

        if self._bridge is not None and hasattr(self._bridge, 'get_profile'):
            res = self._bridge.get_profile(user_id)
            if isinstance(res, Profile):
                return res
            if isinstance(res, dict):
                return Profile(
                    display_name=res.get("displayName") or res.get("display_name", "User"),
                    user_id=user_id,
                    picture_url=res.get("pictureUrl") or res.get("picture_url"),
                    status_message=res.get("statusMessage") or res.get("status_message"),
                    language=res.get("language")
                )

        if self.server_url:
            import requests
            headers = {"Authorization": f"Bearer {self.channel_access_token}"}
            try:
                res = requests.get(
                    f"{self.server_url.rstrip('/')}/api/v1/bot/profile/{user_id}",
                    headers=headers,
                    timeout=timeout or 10,
                )
                if res.status_code == 200:
                    data = res.json()
                    return Profile(
                        display_name=data.get("displayName") or data.get("display_name", "User"),
                        user_id=user_id,
                        picture_url=data.get("pictureUrl") or data.get("picture_url"),
                        status_message=data.get("statusMessage") or data.get("status_message"),
                        language=data.get("language")
                    )
            except Exception:
                pass

        return Profile(display_name=f"User_{user_id[:6]}", user_id=user_id)

    def get_group_member_profile(self, group_id: str, user_id: str, timeout: Optional[int] = None) -> Any:
        return self.get_profile(user_id, timeout=timeout)

    def get_room_member_profile(self, room_id: str, user_id: str, timeout: Optional[int] = None) -> Any:
        return self.get_profile(user_id, timeout=timeout)

