import json
import uuid

import pytest

from vividai.storage import Store


def key():
    return str(uuid.uuid4())


def add(store, node, intent):
    store.begin(node, intent, {"prompt": intent}, "profile-ref", "image")
    path = store.new_path(".png")
    path.write_bytes(b"test-image")
    return store.complete(node, intent, path, {"prompt": intent}, "image")


def test_credentials_projections_and_reopen(tmp_path):
    store = Store(tmp_path)
    ref = store.save_profile("local", "https://vividai.run", "vk_test_secret")
    assert "vk_test_secret" not in json.dumps(store.profiles())
    assert Store(tmp_path).profile(ref)["secret"] == "vk_test_secret"
    with pytest.raises(ValueError):
        store.save_profile("bad", "https://vk_secret@example.org/path", "key")


def test_queue_activation_eviction_leases_and_node_isolation(tmp_path):
    store = Store(tmp_path)
    node, other = key(), key()
    items = [add(store, node, str(i)) for i in range(3)]
    path, release = store.acquire(items[0]["file"])
    store.activate(node, items[0]["id"])
    assert store.selected(node)["snapshot"]["prompt"] == "0"
    add(store, node, "3")
    assert not store.cache_path(items[1]["file"]).exists()
    store.capacity(node, 1)
    assert path.exists()
    assert not store.node(other)["history"]
    release()
    assert not path.exists()
    assert len(Store(tmp_path).node(node)["history"]) == 1
    assert Store(tmp_path).task(node, "3")["state"] == "succeeded"


def test_failed_job_preserves_history_and_manual_activation(tmp_path):
    store, node = Store(tmp_path), key()
    old = add(store, node, "old")
    store.begin(node, "new", {"prompt": "new"}, "ref", "video")
    store.update_task(node, "new", state="running", job_id="job")
    with pytest.raises(ValueError, match="恢复"):
        store.activate(node, old["id"])
    store.update_task(node, "new", state="failed", error="failed")
    assert Store(tmp_path).public_node(node)["task"]["job_id"] == "job"
    store.activate(node, old["id"])
    assert store.selected(node) == old
    assert store.node(node)["active"] is None


@pytest.mark.parametrize("name", ["../outside.png", "not-a-uuid.png", "/tmp/x.mp4"])
def test_cache_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError):
        Store(tmp_path).cache_path(name)


def test_restart_removes_only_owned_orphans(tmp_path):
    store = Store(tmp_path)
    orphan = store.new_path(".part")
    orphan.write_bytes(b"interrupted download")
    unowned = store.cache / "user-file.png"
    unowned.write_bytes(b"keep")
    Store(tmp_path)
    assert not orphan.exists()
    assert unowned.exists()
