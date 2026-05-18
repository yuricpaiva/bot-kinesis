import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


def parse_record_data(record_data: bytes) -> tuple[dict[str, Any] | None, Any, str]:
    try:
        text = record_data.decode("utf-8")
    except UnicodeDecodeError:
        return None, record_data, "binary"

    try:
        raw_payload = json.loads(text)
    except json.JSONDecodeError:
        return None, text, "text"

    payload = extract_payload(raw_payload)
    return payload, raw_payload, "json"


def extract_payload(raw_payload: Any) -> dict[str, Any] | None:
    if not isinstance(raw_payload, dict):
        return None
    data = raw_payload.get("data")
    if isinstance(data, dict) and data.get("objectType"):
        return data
    if raw_payload.get("objectType"):
        return raw_payload
    return raw_payload


def custom_properties(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("customProperties")
    return value if isinstance(value, dict) else {}


def has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def first_sale_type(sale_lines: Any) -> str | None:
    if not isinstance(sale_lines, list):
        return None
    for line in sale_lines:
        if not isinstance(line, dict):
            continue
        props = line.get("customProperties")
        if isinstance(props, dict) and has_value(props.get("saleType")):
            return str(props["saleType"])
    return None


def join_benefit_codes(benefit_data: Any) -> str | None:
    if not isinstance(benefit_data, list):
        return None
    codes = [
        str(item.get("code"))
        for item in benefit_data
        if isinstance(item, dict) and has_value(item.get("code"))
    ]
    return ",".join(codes) if codes else None


def extract_family(tags: Any) -> str | None:
    if not isinstance(tags, list):
        return None
    prefix = "PLUFamilyGroup="
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def xml_vnf(xml_text: Any) -> Decimal | None:
    if not isinstance(xml_text, str) or not xml_text.strip():
        return None
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None

    for element in root.iter():
        tag_name = element.tag.rsplit("}", maxsplit=1)[-1]
        if tag_name == "vNF":
            return to_decimal(element.text)
    return None


def to_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_utc_naive(value: Any) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def to_business_naive(value: Any, timezone_name: str) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)


def to_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
