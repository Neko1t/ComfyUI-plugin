"""Per-node generation intents; current widget changes never imply a new paid task."""

from __future__ import annotations

import asyncio
import uuid

from .client import AmbiguousSubmission, Client, PendingJob, ProviderError, RemoteFailure
from .media import encode, validate_result
from .rules import payload, provider_rule, validate_provider_model


class Service:
    def __init__(self, store, client_factory=Client):
        self.store = store
        self.client_factory = client_factory
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def intent(token: str) -> str:
        if not token:
            return "initial"
        try:
            return str(uuid.UUID(token))
        except (ValueError, AttributeError) as exc:
            raise ValueError("重新生成标记无效") from exc

    def decision(self, key: str, token: str) -> tuple[str, dict | None]:
        intent = self.intent(token)
        node = self.store.node(key)
        active = self.store.task(key, node["active"]) if node["active"] else None
        requested = self.store.task(key, intent)
        if active:
            if active.get("job_id") and active["state"] == "running":
                return "resume", active
            if active["state"] in {"submitting", "prepared"}:
                state = "ambiguous" if active["state"] == "submitting" else "failed"
                active = active | {
                    "state": state,
                    "error": "上次运行在提交过程中中断，请核实后点击下次运行重新生成",
                }
            # A node without a successful material has no cached output to
            # protect. Provider failures and pre-submit failures may retry on
            # the next workflow run; ambiguous submissions remain blocked.
            if not self.store.selected(key) and active["state"] == "failed":
                return "new", None
            if intent != active["intent"] and not requested and token:
                return "new", None
            return "error", active
        selected = self.store.selected(key)
        if token and not requested:
            return "new", None
        if selected:
            return "cached", selected
        if requested:
            return "error", requested | {"error": "历史结果已缺失，请显式重新生成"}
        return "new", None

    async def run(
        self,
        key: str,
        token: str,
        config: str | None,
        snapshot: dict,
        references: dict,
        capacity: int,
        *,
        interrupt=lambda: None,
        max_wait=900,
    ) -> dict:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            self.store.capacity(key, capacity)
            action, record = self.decision(key, token)
            if action == "cached":
                if not self.store.cache_path(record["file"]).is_file():
                    raise ProviderError("选中的素材文件缺失，请手动选择历史或显式重新生成")
                return record
            if action == "error":
                self.store.update_task(
                    key,
                    record["intent"],
                    state=record["state"],
                    error=record.get("error", "任务失败"),
                )
                raise ProviderError(record.get("error", "上次任务失败，请手动启用历史或重新生成"))
            if action == "resume":
                task = record
                snapshot, config = task["snapshot"], task["profile"]
            else:
                # All local validation precedes remote submission and persistence of intent.
                counts = {
                    f"{kind}s": sum(name.startswith(kind + "_") for name in references)
                    for kind in ("image", "video", "audio")
                }
                profile = self.store.profile(config)
                async with self.client_factory(profile) as client:
                    models = await client.models()
                spec = next(
                    (item for item in models if item["id"] == snapshot["model"].strip()), None
                )
                if spec is None:
                    raise ValueError("所选模型当前不可用，请刷新模型列表；已有素材仍可复用")
                if snapshot["rule"].get("_source") in {"default", "provider"} and spec.get(
                    "kind"
                ):
                    snapshot = snapshot | {"rule": provider_rule(spec)}
                validate_provider_model(spec, snapshot, counts)
                body = payload(snapshot, reference_counts=counts)
                intent = self.intent(token)
                # A failed first attempt must be retriable without changing the
                # widget token.  Task intents are unique database keys, so a
                # retry gets a fresh local intent while the visible token keeps
                # its existing meaning (explicit regeneration request).
                if self.store.task(key, intent) is not None:
                    intent = str(uuid.uuid4())
                task = self.store.begin(key, intent, snapshot, config, snapshot["kind"])
                task = self.store.update_task(key, intent, base=profile["base"])
            intent = task["intent"]
            profile = self.store.profile(config)
            if task.get("base", profile["base"]) != profile["base"]:
                raise ProviderError("原任务的 API 地址已被修改；请恢复原连接地址后重连")
            path = None
            try:
                async with self.client_factory(profile) as client:
                    if action == "new":
                        for name, value in references.items():
                            interrupt()
                            upload = await asyncio.to_thread(encode, name.split("_")[0], value)
                            body["refs"].append(await client.upload(upload))
                        interrupt()
                        self.store.update_task(key, intent, state="submitting")
                    else:
                        body = {}

                    def save_job(job_id):
                        self.store.update_task(key, intent, state="running", job_id=job_id)

                    event = await client.generate(
                        body,
                        job_id=task["job_id"],
                        on_job=save_job,
                        interrupt=interrupt,
                        max_wait=max_wait,
                    )
                    path = self.store.new_path(".png" if snapshot["kind"] == "image" else ".mp4")
                    await client.download(event["result"], path, interrupt=interrupt)
                    try:
                        await asyncio.to_thread(validate_result, path, snapshot["kind"])
                    except Exception as exc:
                        raise PendingJob("结果格式校验失败；下次运行将恢复原任务重新下载") from exc
                return self.store.complete(key, intent, path, snapshot, snapshot["kind"])
            except BaseException as exc:
                current = self.store.task(key, intent)
                if isinstance(exc, RemoteFailure):
                    self.store.update_task(key, intent, state="failed", error=str(exc))
                elif isinstance(exc, AmbiguousSubmission) or (
                    current["state"] == "submitting"
                    and not current.get("job_id")
                    and not isinstance(exc, ProviderError)
                ):
                    self.store.update_task(
                        key,
                        intent,
                        state="ambiguous",
                        error="提交状态不明确；请先核实远程任务，再显式重新生成",
                    )
                elif not current.get("job_id"):
                    self.store.update_task(
                        key, intent, state="failed", error="提交前失败，请检查配置后显式重新生成"
                    )
                if path:
                    path.unlink(missing_ok=True)
                if isinstance(exc, (ProviderError, ValueError, asyncio.CancelledError)):
                    raise
                # Don't expose transport URLs, upload URLs or headers through ComfyUI errors.
                raise ProviderError(
                    "VividAI 操作中断，已保留本机任务状态；请查看节点状态"
                ) from None
