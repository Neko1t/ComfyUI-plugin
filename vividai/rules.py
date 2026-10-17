"""Workflow-portable model capabilities; never infer capabilities from model names."""

from __future__ import annotations

import json

DEFAULT_RULE = {
    "max_images": 9,
    "max_videos": 3,
    "max_audios": 3,
    "min_images": 0,
    "min_videos": 0,
    "min_audios": 0,
    "qualities": ["720p", "1080p", "1K", "2K"],
    "ratios": ["16:9", "9:16", "1:1"],
    "duration_required": False,
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
    model, prompt, quality = (snapshot[x].strip() for x in ("model", "prompt", "quality"))
    if not model or not prompt or len(prompt) > 5000 or not quality:
        raise ValueError("请填写模型、提示词（1–5000 字符）和清晰度")
    ratio, duration = snapshot["ratio"].strip(), snapshot["duration"]
    for field, value in (("qualities", quality), ("ratios", ratio)):
        if rule[field] and value not in rule[field]:
            raise ValueError(f"{value} 不在当前模型的 {field} 配置中")
    is_image = snapshot["kind"] == "image"
    if not is_image and ratio not in {"16:9", "9:16"}:
        raise ValueError("VividAI 视频比例仅支持 16:9 或 9:16")
    if not is_image and (duration or rule["duration_required"]):
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
