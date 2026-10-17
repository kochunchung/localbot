"""
localbot.v3 共用的輕量模型基底（取代官方 SDK 的 pydantic 模型）。

- 建構子只接受關鍵字參數（與官方 v3 相同），屬性用 snake_case。
- to_dict() 會轉成 LINE API 的 camelCase JSON。
- from_dict() / from_json() 可直接包住現成的 JSON（常用於 Flex Message）。
"""
import json
import re
from typing import Any, Dict

_CAMEL_RE = re.compile(r"_([a-z0-9])")
_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def to_camel(name: str) -> str:
    return _CAMEL_RE.sub(lambda m: m.group(1).upper(), name)


def to_snake(name: str) -> str:
    return _SNAKE_RE.sub("_", name).lower()


def serialize(value: Any) -> Any:
    if isinstance(value, Model):
        return value.to_dict()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "as_json_dict") and callable(value.as_json_dict):  # v1 模型也能混用
        return value.as_json_dict()
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if v is not None}
    return value


class Model:
    """所有 v3 模型的基底。子類別以 `_type` 宣告 LINE 的 type 值。"""
    _type: Any = None

    def __init__(self, **kwargs: Any):
        object.__setattr__(self, "_raw", None)
        if self._type is not None and "type" not in kwargs:
            self.type = self._type
        for key, value in kwargs.items():
            setattr(self, key, value)

    # ---- 序列化 ----
    def to_dict(self) -> Dict[str, Any]:
        if self._raw is not None:
            return dict(self._raw)
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if key.startswith("_") or value is None:
                continue
            result[to_camel(key)] = serialize(value)
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_str(self) -> str:
        return self.to_json()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        if data is None:
            return None
        obj = cls.__new__(cls)
        object.__setattr__(obj, "_raw", dict(data))
        for key, value in data.items():
            object.__setattr__(obj, to_snake(key), value)
        return obj

    @classmethod
    def from_json(cls, json_str: str):
        return cls.from_dict(json.loads(json_str))

    def __eq__(self, other):
        return isinstance(other, Model) and self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_dict()!r})"


def deep_from_dict(cls, data: Dict[str, Any]):
    """from_dict 的遞迴版：巢狀物件也能用屬性存取（例如 menu.size.width）。"""
    obj = Model.from_dict.__func__(cls, data)  # 不經過子類別覆寫，避免遞迴

    def convert(value):
        if isinstance(value, dict):
            return deep_from_dict(Model, value)
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    for key, value in data.items():
        if isinstance(value, (dict, list)):
            object.__setattr__(obj, to_snake(key), convert(value))
    return obj
