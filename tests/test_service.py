import asyncio
import io
import uuid

import pytest
from PIL import Image

from vividai.client import AmbiguousSubmission, PendingJob, ProviderError, RemoteFailure
from vividai.rules import DEFAULT_RULE, model_rule, payload, ports
from vividai.service import Service
from vividai.storage import Store


class FakeClient:
    submissions = []
    resumes = []
    failure = None

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def models(self):
        return ["model-with-changing-name"]

    async def generate(self, payload, *, job_id, on_job, **kwargs):
        if job_id:
            self.resumes.append(job_id)
        else:
            self.submissions.append(payload)
            if isinstance(self.failure, AmbiguousSubmission):
                raise self.failure
            on_job("original-job")
        if self.failure:
            raise self.failure
        return {"result": "https://unused.test/result"}

    async def download(self, url, path, **kwargs):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
        path.write_bytes(buffer.getvalue())


@pytest.fixture
def setup(tmp_path):
    FakeClient.submissions, FakeClient.resumes, FakeClient.failure = [], [], None
    store = Store(tmp_path)
    ref = store.save_profile("test", "https://vividai.run", "vk_local_test")
    snapshot = {
        "model": "model-with-changing-name",
        "prompt": "before",
        "quality": "1K",
        "ratio": "1:1",
        "duration": 0,
        "kind": "image",
        "rule": DEFAULT_RULE.copy(),
    }
    return store, Service(store, FakeClient), ref, snapshot, str(uuid.uuid4())


def test_explicit_generation_reuse_and_manual_history(setup):
    store, service, ref, snapshot, node = setup

    async def run():
        first = await service.run(node, "", ref, snapshot, {}, 3)
        changed = snapshot | {"prompt": "after", "model": "removed"}
        assert await service.run(node, "", None, changed, {}, 3) == first
        token = str(uuid.uuid4())
        second = await service.run(node, token, ref, snapshot | {"prompt": "new"}, {}, 3)
        assert second != first
        assert await service.run(node, token, None, changed, {}, 3) == second
        store.activate(node, first["id"])
        assert await service.run(node, token, None, changed, {}, 3) == first
        assert first["snapshot"]["prompt"] == "before"

    asyncio.run(run())
    assert len(FakeClient.submissions) == 2


def test_restart_reconnect_uses_original_snapshot_and_profile(setup):
    store, service, ref, snapshot, node = setup
    FakeClient.failure = PendingJob("wait")

    async def run():
        with pytest.raises(PendingJob):
            await service.run(node, "", ref, snapshot, {}, 3)
        assert store.task(node, "initial")["job_id"] == "original-job"
        assert service.decision(node, "")[0] == "resume"
        FakeClient.failure = None
        restarted = Service(Store(store.root), FakeClient)
        result = await restarted.run(node, "", None, {}, {}, 3)
        assert result["snapshot"] == snapshot

    asyncio.run(run())
    assert len(FakeClient.submissions) == 1
    assert FakeClient.resumes == ["original-job"]


def test_ambiguous_never_resubmits_and_failed_does_not_fallback(setup):
    store, service, ref, snapshot, node = setup

    async def run():
        old = await service.run(node, "", ref, snapshot, {}, 3)
        FakeClient.failure = AmbiguousSubmission("unknown")
        token = str(uuid.uuid4())
        with pytest.raises(AmbiguousSubmission):
            await service.run(node, token, ref, snapshot, {}, 3)
        for _ in range(2):
            with pytest.raises(ProviderError, match="不明确"):
                await service.run(node, token, ref, snapshot, {}, 3)
        assert store.selected(node) == old
        store.activate(node, old["id"])
        assert await service.run(node, token, None, {}, {}, 3) == old
        FakeClient.failure = RemoteFailure("provider failed")
        token = str(uuid.uuid4())
        with pytest.raises(RemoteFailure):
            await service.run(node, token, ref, snapshot, {}, 3)
        with pytest.raises(ProviderError, match="provider failed"):
            await service.run(node, token, None, {}, {}, 3)
        assert store.selected(node) == old

    asyncio.run(run())
    assert len(FakeClient.submissions) == 3


def test_rules_bounds_and_basic_validation():
    rule = model_rule('{"new":{"max_audios":0,"max_images":2}}', "new")
    assert ports(rule) == ["image_1", "image_2", "video_1", "video_2", "video_3"]
    with pytest.raises(ValueError):
        model_rule('{"new":{"max_images":10}}', "new")
    snapshot = {
        "model": "new",
        "prompt": "p",
        "quality": "720p",
        "ratio": "16:9",
        "duration": 4,
        "kind": "video",
        "rule": rule | {"durations": [5, 10]},
    }
    with pytest.raises(ValueError, match="时长"):
        payload(snapshot, reference_counts={})
