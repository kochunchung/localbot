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

