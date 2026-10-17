"""Workflow-portable model capabilities; never infer capabilities from model names."""

from __future__ import annotations

import json
from collections.abc import Mapping

DEFAULT_RULE = {
    "max_images": 9,
    "max_videos": 3,
    "max_audios": 3,
    "min_images": 0,
    "min_videos": 0,
    "min_audios": 0,
    "qualities": ["720p", "1080p", "1K", "2K"],
    "ratios": ["16:9", "9:16", "1:1"],
    # VividAI's current /v1/generate contract requires duration for video
    # generation. Image payloads ignore this field; individual models can
    # still override it in the workflow's per-model capability configuration.
    "duration_required": True,
    "duration_min": 1,
    "duration_max": 30,
    "durations": [],
}


def model_rule(rules_json: str, model: str) -> dict:
    try:
        rules = json.loads(rules_json or "{}")
        raw = rules.get(model, {})
        if not isinstance(raw, dict):
            raise ValueError("rule is not an object")
        rule = DEFAULT_RULE | raw
        for kind, bound in (("images", 9), ("videos", 3), ("audios", 3)):
            for prefix in ("max", "min"):
                value = rule[f"{prefix}_{kind}"]
                if type(value) is not int or not 0 <= value <= bound:
                    raise ValueError("invalid reference limit")
            if rule[f"min_{kind}"] > rule[f"max_{kind}"]:
                raise ValueError("min > max")
        for field in ("qualities", "ratios"):
            if not isinstance(rule[field], list) or not all(
                isinstance(x, str) and x for x in rule[field]
            ):
                raise ValueError("invalid options")
        if not isinstance(rule["durations"], list) or not all(
            type(x) is int and 1 <= x <= 3600 for x in rule["durations"]
        ):
            raise ValueError("invalid durations")
        if not (
            type(rule["duration_min"]) is int
            and type(rule["duration_max"]) is int
            and 1 <= rule["duration_min"] <= rule["duration_max"] <= 3600
            and type(rule["duration_required"]) is bool
        ):
            raise ValueError("invalid duration range")
        return rule
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("模型能力配置无效，请检查展开配置项") from exc


def _content_text(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        raise ValueError("OpenAI 内容必须是字符串或内容数组")
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, Mapping):
            raise ValueError("OpenAI 内容片段格式无效")
        kind = item.get("type")
        if kind in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
            parts.append(item["text"])
            continue
        if kind in {"image_url", "input_image", "input_file", "file"}:
            raise ValueError(
                "当前文生图节点不能把 OpenAI 图像/文件内容当作提示词，请使用参考素材节点"
            )
        raise ValueError("OpenAI 内容片段必须包含可识别的文本")
    return parts


def _openai_text(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        if "messages" in value:
            return _openai_text(value["messages"])
        elif "input" in value:
            return _openai_text(value["input"])
        elif "content" in value:
            return _content_text(value["content"])
        elif "text" in value and isinstance(value["text"], str):
            return [value["text"]]
        else:
            raise ValueError("OpenAI 输入必须包含 messages、input 或 content")
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, Mapping) and "content" in item:
                message = _content_text(item["content"])
                role = item.get("role")
                if role and role != "user":
                    parts.extend([f"{role}: {text}" for text in message])
                else:
                    parts.extend(message)
            else:
                parts.extend(_content_text(item))
        return parts
    raise ValueError("OpenAI 输入格式无效")


def normalize_prompt(prompt) -> str:
    """Accept plain text or JSON/OpenAI message content and return VividAI text."""
    value = prompt
    if isinstance(value, str):
        value = value.strip()
        if value[:1] in {"{", "["}:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                # A normal prompt may begin with punctuation that resembles JSON.
                return value
    pieces = [piece.strip() for piece in _openai_text(value) if piece.strip()]
    result = "\n\n".join(pieces)
    if not result or len(result) > 5000:
        raise ValueError("请填写提示词（1–5000 字符）")
    return result


def ports(rule: dict) -> list[str]:
    return [
        f"{kind}_{i}"
        for kind, plural in (
            ("image", "images"),
            ("video", "videos"),
            ("audio", "audios"),
        )
        for i in range(1, rule[f"max_{plural}"] + 1)
    ]


def payload(snapshot: dict, *, reference_counts: dict) -> dict:
    rule = snapshot["rule"]
    model = snapshot["model"].strip()
    prompt = normalize_prompt(snapshot["prompt"])
    quality = snapshot["quality"].strip()
    if not model or not quality:
        raise ValueError("请填写模型、提示词（1–5000 字符）和清晰度")
    ratio, duration = snapshot["ratio"].strip(), snapshot["duration"]
    for field, value in (("qualities", quality), ("ratios", ratio)):
        if rule[field] and value not in rule[field]:
            raise ValueError(f"{value} 不在当前模型的 {field} 配置中")
    is_image = snapshot["kind"] == "image"
    if not is_image and ratio not in {"16:9", "9:16"}:
        raise ValueError("VividAI 视频比例仅支持 16:9 或 9:16")
    if not is_image and (duration or rule["duration_required"]):
        if rule["duration_required"] and duration == 0:
            raise ValueError("请填写视频时长（秒）")
        if (
            type(duration) is not int
            or not rule["duration_min"] <= duration <= rule["duration_max"]
        ):
            raise ValueError("视频时长超出模型配置范围")
        if rule["durations"] and duration not in rule["durations"]:
            raise ValueError("视频时长不在模型支持的可选值中")
    for plural in ("images", "videos", "audios"):
        count = reference_counts.get(plural, 0)
        if not rule[f"min_{plural}"] <= count <= rule[f"max_{plural}"]:
            raise ValueError(f"{plural} 数量不满足模型能力配置")
    result = {"model": model, "prompt": prompt, "quality": quality, "refs": []}
    if ratio:
        result["ratio"] = ratio
    if not is_image and duration:
        result["duration"] = duration
    return result
