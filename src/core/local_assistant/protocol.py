"""Small, dependency-free parser for the known useful NTQQ message fields."""

from __future__ import annotations

from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET


class ProtoError(ValueError):
    pass


@dataclass(frozen=True)
class WireField:
    number: int
    wire_type: int
    value: int | bytes


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, offset
        shift += 7
    raise ProtoError("invalid protobuf varint")


def wire_fields(data: bytes | None) -> list[WireField]:
    if not data:
        return []
    result: list[WireField] = []
    offset = 0
    while offset < len(data):
        key, offset = _varint(data, offset)
        number, wire_type = key >> 3, key & 7
        if number <= 0:
            raise ProtoError("invalid protobuf field number")
        if wire_type == 0:
            value, offset = _varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ProtoError("truncated fixed64")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtoError("truncated length-delimited field")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ProtoError("truncated fixed32")
            value = data[offset:end]
            offset = end
        else:
            raise ProtoError("unsupported protobuf wire type")
        result.append(WireField(number, wire_type, value))
    return result


def _text(value: int | bytes | None) -> str:
    if not isinstance(value, bytes):
        return ""
    return value.decode("utf-8", errors="replace").strip()


def _md5(value: int | bytes | None) -> str:
    if not isinstance(value, bytes) or not value:
        return ""
    candidate = value.decode("ascii", errors="ignore").strip()
    if len(candidate) == 32 and all(char in "0123456789abcdefABCDEF" for char in candidate):
        return candidate.lower()
    return value.hex()


def _visible_xml(value):
    text = _text(value)
    if not text or len(text) > 200000 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        return ''
    try:
        root = ET.fromstring(text)
        return ''.join((node.text or '') + (node.attrib.get('txt') or node.attrib.get('text') or '') + (node.tail or '') for node in root.iter()).strip()
    except ET.ParseError:
        return text if '<' not in text else ''


def decode_message_details(blob: bytes | None, outer_type: int, _depth: int = 0) -> dict[str, object]:
    """Return display text, content classification and safe media references.

    The top-level field 40800 holds repeated message segments. Segment 45101
    contains visible text and 45002 describes the segment type. Unknown data is
    deliberately retained by the caller as a BLOB and reported as partial.
    """
    if not blob:
        return {"text": "[本地未缓存消息正文]", "content_kind": "正文缺失", "segment_count": 0, "semantic_status": 0, "media": [], "replies": []}
    try:
        top = wire_fields(blob)
        contents = [field.value for field in top if field.number == 40800 and isinstance(field.value, bytes)]
        if not contents and any(field.number in (45002, 45101) for field in top):
            contents = [blob]
        texts: list[str] = []
        labels: list[str] = []
        media: list[dict[str, object]] = []
        replies = []
        for content in contents:
            content_type = 0
            fields = wire_fields(content)
            by_number = {field.number: field.value for field in fields}
            for field in fields:
                if field.number == 45101 and isinstance(field.value, bytes):
                    text = _text(field.value)
                    if text:
                        texts.append(text)
                if field.number == 45002 and isinstance(field.value, int):
                    content_type = field.value
            labels.append({1: "文本", 2: "图片", 3: "文件", 4: "语音", 5: "视频", 6: "表情", 7: "引用回复", 8: "系统提示", 10: "卡片", 11: "表情", 14: "Markdown", 16: "合并转发"}.get(content_type, "其他内容"))
            if content_type == 7:
                nested = by_number.get(47710)
                quoted = decode_message_details(nested, 2, _depth + 1) if isinstance(nested, bytes) and _depth < 4 else {}
                summary = _text(by_number.get(47413)) or _text(by_number.get(47713)) or quoted.get('text', '')
                replies.append({'text': summary, 'sender': _text(by_number.get(47421)) or _text(by_number.get(47705)),
                                'sequence': str(by_number.get(47402) or ''), 'sent_at': by_number.get(47404) or 0})
            if content_type == 8:
                notice = _visible_xml(by_number.get(48214))
                # Some QQ versions wrap the gray-tip XML in ReplyExtension.
                if not notice:
                    for field in fields:
                        if isinstance(field.value, bytes) and field.number not in (45101, 47710):
                            try:
                                nested_fields = wire_fields(field.value)
                                notice = next((_visible_xml(item.value) for item in nested_fields if item.number == 48214), '')
                            except ProtoError:
                                continue
                            if notice:
                                break
                if notice:
                    texts.append(notice)
            if not any(field.number == 45101 for field in fields) and content_type in (6, 11, 21):
                fallback_text = _text(by_number.get(47602)) or _text(by_number.get(80900)) or _text(by_number.get(48153))
                if fallback_text:
                    texts.append(fallback_text)
            media_sub = by_number.get(45003, 0)
            width = by_number.get(45411, 0)
            height = by_number.get(45412, 0)
            if content_type == 2 and media_sub not in (2, 7, 11):
                item = {
                    "type": "image",
                    "filename": _text(by_number.get(45402)) or _text(by_number.get(45403)),
                    "width": width if isinstance(width, int) else 0,
                    "height": height if isinstance(height, int) else 0,
                    "filesize": by_number.get(45405, 0) if isinstance(by_number.get(45405, 0), int) else 0,
                    "md5": _md5(by_number.get(45406)) or _md5(by_number.get(45424)),
                    "local_path": _text(by_number.get(45812)) or _text(by_number.get(45814)) or _text(by_number.get(45403)),
                    "local_paths": list(dict.fromkeys(filter(None, (_text(by_number.get(n)) for n in (45812, 45814, 45403))))),
                    "cdn_url": _text(by_number.get(45802)) or _text(by_number.get(45803)) or _text(by_number.get(45804)),
                }
                media.append(item)
        if texts:
            display_text = "\n".join(texts)
        elif media:
            filename = str(media[0].get("filename") or "")
            display_text = f"[图片{': ' + filename if filename else ''}]"
        elif replies:
            display_text = "[引用回复，引用内容见下方]"
        else:
            fallback = {3: "文件", 8: "合并转发", 9: "表情回应", 11: "合并转发", 17: "系统通知", 19: "通话"}.get(outer_type, "+".join(dict.fromkeys(labels)) or "非文本消息")
            display_text = f"[{fallback}]"
        return {
            "text": display_text,
            "content_kind": "+".join(dict.fromkeys(labels)) or ("图片" if media else "非文本消息"),
            "segment_count": len(contents),
            "semantic_status": 1,
            "media": media,
            "replies": replies,
        }
    except ProtoError:
        return {"text": "[未能解析的消息内容]", "content_kind": "未知内容", "segment_count": 0, "semantic_status": -1, "media": []}


def decode_message_body(blob: bytes | None, outer_type: int) -> tuple[str, str, int, int]:
    details = decode_message_details(blob, outer_type)
    return (
        str(details["text"]),
        str(details["content_kind"]),
        int(details["segment_count"]),
        int(details["semantic_status"]),
    )


def decode_cached_replies(blob):
    """40900 snapshots are context, never substitute their text for the sender."""
    result = []
    try:
        for snapshot in wire_fields(blob):
            if snapshot.number != 40900 or not isinstance(snapshot.value, bytes): continue
            fields = wire_fields(snapshot.value)
            values = {field.number: field.value for field in fields}
            for field in fields:
                if field.number != 40800 or not isinstance(field.value, bytes): continue
                details = decode_message_details(field.value, int(values.get(40011, 2)))
                text = details['text']
                if text and not text.startswith('['):
                    result.append({'text':text,'sender':_text(values.get(40093)), 'sequence':str(values.get(40003) or ''), 'sent_at':values.get(40050) or 0, 'source':'缓存引用'})
            if len(result) >= 20: break
    except (ProtoError, ValueError, TypeError): pass
    return result[:20]
