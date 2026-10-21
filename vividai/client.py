"""VividAI's unified API: one submission, resumable NDJSON subscription."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .rules import provider_rule


class ProviderError(RuntimeError):
    pass


class AmbiguousSubmission(ProviderError):
    """Submission might have been accepted; resubmission requires a new explicit intent."""


class PendingJob(ProviderError):
    """Known job remains recoverable on the next run."""


class RemoteFailure(ProviderError):
    pass


@dataclass(frozen=True)
class Upload:
    kind: str
    mime: str
    content: bytes


UPLOAD_MIMES = {
    "image": {"image/png", "image/jpeg", "image/webp"},
    "video": {"video/mp4", "video/webm", "video/quicktime"},
    "audio": {"audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg"},
}


class Client:
    def __init__(self, profile: dict, *, transport=None):
        self.base = profile["base"]
        self.secret = profile["secret"]
        timeout = httpx.Timeout(45, connect=15, write=60, pool=15)
        # API redirects are deliberately not followed with Bearer authentication.
        self.api = httpx.AsyncClient(
            base_url=self.base,
            headers={"Authorization": f"Bearer {self.secret}"},
            timeout=timeout,
            transport=transport,
        )
        self.files = httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=True)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.api.aclose()
        await self.files.aclose()

    def _message(self, message) -> str:
        return str(message).replace(self.secret, "[已隐藏]")[:500]

    async def _status(self, response: httpx.Response):
        if response.is_success:
            return
        await response.aread()
        try:
            error = response.json().get("error", {})
            message = error.get("message", "请求被服务端拒绝") if isinstance(error, dict) else error
        except (ValueError, AttributeError):
            message = "请求被服务端拒绝"
        raise ProviderError(f"VividAI HTTP {response.status_code}: {self._message(message)}")

    async def models(self) -> list[dict]:
        response = await self.api.get("/v1/models")
        await self._status(response)
        try:
            data = response.json()
            # The current VividAI response is a top-level array. Keep support
            # for older OpenAI-style gateways that wrap the array in `data`.
            if isinstance(data, dict):
                data = data["data"]
            if not isinstance(data, list):
                raise TypeError("models is not a list")
            models = {}
            for item in data:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    raise TypeError("invalid model")
                model_id = item["id"].strip()
                if not model_id:
                    raise ValueError("empty model ID")
                if "kind" in item and not isinstance(item["kind"], str):
                    raise TypeError("invalid model kind")
                provider_rule(item)
                models[model_id] = item | {"id": model_id}
            return list(models.values())
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("模型列表响应格式不正确") from exc

    @staticmethod
    def _file_url(url: str):
        parts = urlsplit(url)
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username
            or parts.password
            or (parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ProviderError("素材地址必须使用 HTTPS")

    async def upload(self, upload: Upload) -> str:
        limit = (20 if upload.kind == "image" else 40) * 1024 * 1024
        if upload.mime not in UPLOAD_MIMES.get(upload.kind, set()):
            raise ValueError("不支持的参考素材格式")
        if not upload.content or len(upload.content) > limit:
            raise ValueError(f"{upload.kind} 素材须非空且不超过 {limit // 1024 // 1024} MB")
        response = await self.api.post(
            "/v1/uploads", json={"kind": upload.kind, "mime": upload.mime}
        )
        await self._status(response)
        try:
            data = response.json()
            self._file_url(data["url"])
            key = data["key"]
            if not isinstance(key, str) or not key:
                raise ValueError("missing key")
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("上传地址响应不完整") from exc
        response = await self.files.put(
            data["url"], content=upload.content, headers={"Content-Type": upload.mime}
        )
        if not response.is_success:
            raise ProviderError(f"参考素材上传失败 HTTP {response.status_code}")
        return key

    async def generate(
        self,
        payload: dict,
        *,
        job_id: str | None,
        on_job: Callable[[str], None],
        interrupt: Callable[[], None] = lambda: None,
        max_wait: float = 900,
    ) -> dict:
        current_job = job_id
        deadline = time.monotonic() + max_wait
        failures = 0
        try:
            async with asyncio.timeout(max_wait):
                while time.monotonic() < deadline:
                    interrupt()
                    body = {"jobId": current_job} if current_job else payload
                    try:
                        async with self.api.stream(
                            "POST",
                            "/v1/generate",
                            json=body,
                            headers={"X-Wait-Seconds": "60"},
                        ) as response:
                            if response.status_code >= 500 and not current_job:
                                raise AmbiguousSubmission(
                                    "提交返回服务错误，任务状态不明确；禁止自动重提"
                                )
                            await self._status(response)
                            async for line in response.aiter_lines():
                                interrupt()
                                if not line.strip():
                                    continue
                                event = json.loads(line)
                                received = event.get("jobId")
                                if received:
                                    if not isinstance(received, str) or (
                                        current_job and current_job != received
                                    ):
                                        raise ValueError("jobId mismatch")
                                    if not current_job:
                                        on_job(received)  # Commit before reading any more bytes.
                                        current_job = received
                                if not current_job:
                                    raise ValueError("missing jobId")
                                if event.get("status") == "succeeded":
                                    self._file_url(event["result"])
                                    return event
                                if event.get("status") == "failed":
                                    raise RemoteFailure(
                                        self._message(event.get("error", "生成失败"))
                                    )
                            if not current_job:
                                raise ValueError("stream ended before jobId")
                        failures = 0
                    except (httpx.TransportError, ValueError, KeyError) as exc:
                        if not current_job:
                            raise AmbiguousSubmission(
                                "提交中断且未取得 jobId，任务状态不明确；禁止自动重提"
                            ) from exc
                        failures += 1
                        if failures >= 4:
                            raise PendingJob(
                                "原任务连接暂时不可用；下次运行会恢复同一任务"
                            ) from exc
                    await asyncio.sleep(min(0.5 * 2**failures, 4))
        except TimeoutError as exc:
            if current_job:
                raise PendingJob("等待已达上限；下次运行会恢复同一任务") from exc
            raise AmbiguousSubmission("提交等待超时且无 jobId，请先核实远程任务") from exc
        raise PendingJob("等待已达上限；下次运行会恢复同一任务")

    async def download(self, url: str, path: Path, *, interrupt=lambda: None):
        self._file_url(url)
        part = path.with_suffix(".part")
        try:
            size = 0
            async with self.files.stream("GET", url) as response:
                if not response.is_success:
                    raise PendingJob("结果下载失败；下次运行将重新订阅原任务并获取结果地址")
                with part.open("wb") as stream:
                    async for chunk in response.aiter_bytes():
                        interrupt()
                        size += len(chunk)
                        if size > 2 * 1024**3:
                            raise ProviderError("结果超过本机单文件 2 GB 上限")
                        stream.write(chunk)
            if not size:
                raise PendingJob("结果文件为空；请恢复原任务重试下载")
            os.replace(part, path)
        except httpx.TransportError as exc:
            raise PendingJob("结果下载中断；下次运行恢复原任务") from exc
        finally:
            part.unlink(missing_ok=True)
