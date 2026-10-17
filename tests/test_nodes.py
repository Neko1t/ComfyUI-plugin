"""Run against an actual ComfyUI checkout using COMFYUI_PATH (no schema stubs)."""

import asyncio
import gc
import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest
from PIL import Image

if os.environ.get("COMFYUI_PATH"):
    sys.path.insert(0, str(Path(os.environ["COMFYUI_PATH"]).resolve()))
pytest.importorskip("comfy_api.latest")

from vividai import runtime  # noqa: E402
from vividai.media import native_output  # noqa: E402
from vividai.nodes import VividAIExtension, VividAIReferenceVideo, VividAITextToImage  # noqa: E402
from vividai.service import Service  # noqa: E402
from vividai.storage import Store  # noqa: E402


def test_legacy_mapping_exposes_the_v3_nodes():
    root = Path(__file__).resolve().parents[1]
    # ComfyUI's load_custom_node uses the absolute directory as its module name.
    module_name = str(root).replace(".", "_x_")
    spec = importlib.util.spec_from_file_location(
        module_name, root / "__init__.py", submodule_search_locations=[str(root)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert set(module.NODE_CLASS_MAPPINGS) == {
            "VividAIConfig",
            "VividAITextToImage",
            "VividAITextToVideo",
            "VividAIReferenceVideo",
        }
        for node_id, node_class in module.NODE_CLASS_MAPPINGS.items():
            info = node_class.GET_NODE_INFO_V1()
            assert info["name"] == node_id
            assert info["display_name"] == module.NODE_DISPLAY_NAME_MAPPINGS[node_id]
            assert node_class.INPUT_TYPES()["required"]
            assert callable(getattr(node_class, node_class.FUNCTION))
    finally:
        sys.modules.pop(spec.name, None)


def test_official_schemas_and_lazy_boundaries(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(runtime, "_service", Service(store))
    classes = asyncio.run(VividAIExtension().get_node_list())
    assert [cls.GET_SCHEMA().node_id for cls in classes] == [
        "VividAIConfig",
        "VividAITextToImage",
        "VividAITextToVideo",
        "VividAIReferenceVideo",
    ]
    schema = VividAIReferenceVideo.GET_SCHEMA()
    refs = [x for x in schema.inputs if x.id.startswith(("image_", "video_", "audio_"))]
    assert len(refs) == 15 and all(x.lazy for x in refs)
    assert VividAIReferenceVideo.RETURN_TYPES == ["VIDEO"]
    key = str(uuid.uuid4())
    kwargs = dict(
        node_key=key,
        model="new",
        model_rules='{"new":{"max_audios":0}}',
        config=None,
        image_1=None,
        video_1=None,
        audio_1=None,
    )
    assert VividAIReferenceVideo.check_lazy_status(**kwargs) == ["config", "image_1", "video_1"]
    store.begin(key, "initial", {}, "ref", "image")
    path = store.new_path(".png")
    Image.new("RGB", (4, 4)).save(path)
    store.complete(key, "initial", path, {}, "image")
    assert VividAIReferenceVideo.check_lazy_status(**(kwargs | {"model_rules": "broken"})) == []
    assert VividAITextToImage.fingerprint_inputs() != VividAITextToImage.fingerprint_inputs()


def test_native_video_lease_lives_as_long_as_video_object(tmp_path):
    import av
    import numpy as np

    store, key = Store(tmp_path), str(uuid.uuid4())
    store.capacity(key, 1)
    store.begin(key, "initial", {}, "ref", "video")
    path = store.new_path(".mp4")
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    item = store.complete(key, "initial", path, {}, "video")
    video = native_output(store, item)
    assert video.get_dimensions() == (16, 16)
    store.begin(key, "other", {}, "ref", "image")
    other = store.new_path(".png")
    Image.new("RGB", (4, 4)).save(other)
    store.complete(key, "other", other, {}, "image")
    assert path.exists()
    del video
    gc.collect()
    assert not path.exists()
