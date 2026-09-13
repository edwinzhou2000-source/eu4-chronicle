"""Clausewitz 文本分词与轻量 AST。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObjectNode:
    values: dict[str, Any] = field(default_factory=dict)
    lists: dict[str, list[Any]] = field(default_factory=dict)
    # 同名字段多次出现时保留全部，便于战争/关系等
    multi: dict[str, list[Any]] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.values:
            return self.values[key]
        if key in self.lists:
            return self.lists[key]
        if key in self.multi:
            return self.multi[key]
        return default

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, ObjectNode):
            return default
        return str(value).strip('"')

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self.get_float(key, float(default)))

    def get_object(self, key: str) -> ObjectNode | None:
        value = self.get(key)
        if isinstance(value, ObjectNode):
            return value
        return None

    def get_list(self, key: str) -> list[Any]:
        if key in self.lists:
            return self.lists[key]
        value = self.get(key)
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    def all_objects(self, key: str) -> list[ObjectNode]:
        items: list[Any] = []
        if key in self.multi:
            items.extend(self.multi[key])
        elif key in self.values and isinstance(self.values[key], ObjectNode):
            items.append(self.values[key])
        return [x for x in items if isinstance(x, ObjectNode)]


def _tokenize(text: str) -> list[str]:
    """按 Clausewitz 规则分词：保留引号字符串、=、{}。"""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] not in "\n\r":
                i += 1
            continue
        if ch in "{}=":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            j = i + 1
            buf: list[str] = ['"']
            while j < n:
                c = text[j]
                buf.append(c)
                if c == '"' and text[j - 1] != "\\":
                    j += 1
                    break
                j += 1
            tokens.append("".join(buf))
            i = j
            continue
        j = i
        while j < n and (not text[j].isspace()) and text[j] not in "{}=#":
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def _store(node: ObjectNode, key: str, value: Any) -> None:
    if key in node.values:
        existing = node.values.pop(key)
        node.multi.setdefault(key, []).append(existing)
        node.multi[key].append(value)
        return
    if key in node.multi:
        node.multi[key].append(value)
        return
    node.values[key] = value


def _coerce(raw: str) -> Any:
    if raw in {"yes", "no"}:
        return raw == "yes"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def parse_clausewitz(text: str) -> ObjectNode:
    """解析 Clausewitz 文本：正确区分对象与列表。"""
    tokens = _tokenize(text)
    root = ObjectNode()
    _consume_block(tokens, 0, root, until_brace=False)
    return root


# 兼容旧名
parse_clausewitz_v2 = parse_clausewitz


def _consume_block(
    tokens: list[str],
    index: int,
    node: ObjectNode,
    *,
    until_brace: bool,
) -> int:
    i = index
    n = len(tokens)
    pending_list_key: str | None = None
    list_buf: list[Any] | None = None

    def flush_list() -> None:
        nonlocal pending_list_key, list_buf
        if pending_list_key is not None and list_buf is not None:
            node.lists[pending_list_key] = list_buf
        pending_list_key = None
        list_buf = None

    while i < n:
        tok = tokens[i]
        if tok == "}" and until_brace:
            flush_list()
            return i + 1
        if tok == "{":
            # 匿名块，跳过
            skip = ObjectNode()
            i = _consume_block(tokens, i + 1, skip, until_brace=True)
            continue

        key = tok.strip('"')
        i += 1
        if i < n and tokens[i] == "=":
            flush_list()
            i += 1
            if i >= n:
                break
            if tokens[i] == "{":
                # 窥探：对象还是列表？
                peek = i + 1
                is_list = False
                if peek < n and tokens[peek] != "}":
                    # 若下一个 token 后不是 =，且不是 }，倾向列表；
                    # 若存在 key= 模式则为对象。
                    is_list = _looks_like_list(tokens, peek)
                if is_list:
                    values, i = _parse_list(tokens, i + 1)
                    node.lists[key] = values
                else:
                    child = ObjectNode()
                    i = _consume_block(tokens, i + 1, child, until_brace=True)
                    if not child.values and not child.multi and not child.lists:
                        node.lists[key] = []
                    else:
                        _store(node, key, child)
            else:
                _store(node, key, _coerce(tokens[i].strip('"')))
                i += 1
            continue

        # 裸值：属于正在进行的列表（Clausewitz 里少见在对象顶层）
        if list_buf is None:
            pending_list_key = "_anon"
            list_buf = []
        list_buf.append(_coerce(key))
    flush_list()
    return i


def _looks_like_list(tokens: list[str], start: int) -> bool:
    """从 { 之后的位置判断是列表还是对象。"""
    depth = 0
    i = start
    n = len(tokens)
    saw_assign = False
    saw_bare = False
    while i < n:
        tok = tokens[i]
        if tok == "{":
            depth += 1
            i += 1
            continue
        if tok == "}":
            if depth == 0:
                break
            depth -= 1
            i += 1
            continue
        if depth == 0:
            if i + 1 < n and tokens[i + 1] == "=":
                saw_assign = True
                # 跳过 key = value / key = {
                i += 2
                if i < n and tokens[i] == "{":
                    # 跳过嵌套块
                    nest = 1
                    i += 1
                    while i < n and nest:
                        if tokens[i] == "{":
                            nest += 1
                        elif tokens[i] == "}":
                            nest -= 1
                        i += 1
                    continue
                i += 1
                continue
            saw_bare = True
            i += 1
            continue
        i += 1
    if saw_bare and not saw_assign:
        return True
    if saw_assign and not saw_bare:
        return False
    # 混合或空：按对象处理更安全；空列表也当对象
    return saw_bare and not saw_assign


def _parse_list(tokens: list[str], start: int) -> tuple[list[Any], int]:
    values: list[Any] = []
    i = start
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "}":
            return values, i + 1
        if tok == "{":
            child = ObjectNode()
            i = _consume_block(tokens, i + 1, child, until_brace=True)
            values.append(child)
            continue
        values.append(_coerce(tok.strip('"')))
        i += 1
    return values, i
