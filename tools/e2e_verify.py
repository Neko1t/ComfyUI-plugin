"""Verify actual ComfyUI execution against tools/mock_provider.py on loopback."""

import copy
import json
import time
import uuid
from pathlib import Path

import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:8199", timeout=20) as client:
        response = client.post(
            "/vividai/profiles",
            json={
                "name": "E2E mock",
                "base": "http://127.0.0.1:8200",
                "secret": "vk_dummy_e2e",
            },
        )
        response.raise_for_status()
        ref = response.json()["id"]
        baseline = httpx.get("http://127.0.0.1:8200/__state").json()
        key = str(uuid.uuid4())
        inputs = {
            "config": ["1", 0],
            "node_key": key,
            "generation_token": "",
            "model": "mock-image",
            "prompt": "image",
            "quality": "1K",
            "ratio": "1:1",
            "duration": 0,
            "history_capacity": 3,
            "model_rules": "{}",
        }
        graph = {
            "1": {"class_type": "VividAIConfig", "inputs": {"config_ref": ref}},
            "2": {"class_type": "VividAITextToImage", "inputs": inputs},
            "3": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["2", 0],
                    "filename_prefix": "vividai-e2e/image",
                },
            },
        }

        def execute(graph, success=True):
            response = client.post("/prompt", json={"prompt": graph})
            assert response.status_code == 200, response.text
            prompt_id = response.json()["prompt_id"]
            for _ in range(120):
                result = client.get(f"/history/{prompt_id}").json()
                if prompt_id in result:
                    record = result[prompt_id]
                    assert (record["status"]["status_str"] == "success") == success, record
                    return record
                time.sleep(0.25)
            raise AssertionError("ComfyUI execution did not finish in 30 seconds")

        execute(graph)
        first = client.get(f"/vividai/nodes/{key}").json()["selected"]
        inputs.update(prompt="modified but reuse", model="removed-model")
        execute(graph)
        assert client.get(f"/vividai/nodes/{key}").json()["selected"] == first
        inputs.update(prompt="disconnect", model="mock-image", generation_token=str(uuid.uuid4()))
        execute(graph)
        inputs.update(prompt="fail", generation_token=str(uuid.uuid4()))
        execute(graph, success=False)
        state = client.get(f"/vividai/nodes/{key}").json()
        assert state["task"]["state"] == "failed" and len(state["history"]) == 2
        client.post(
            f"/vividai/nodes/{key}/activate", json={"material_id": first}
        ).raise_for_status()
        execute(graph)
        # The native VIDEO output must be accepted and saved by ComfyUI's own SaveVideo.
        video_graph = copy.deepcopy(graph)
        video = video_graph["2"]
        video["class_type"] = "VividAITextToVideo"
        video["inputs"].update(
            node_key=str(uuid.uuid4()),
            generation_token="",
            model="mock-video-933",
            prompt="video",
            quality="720p",
            ratio="16:9",
        )
        video_graph["3"] = {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["2", 0],
                "filename_prefix": "vividai-e2e/video",
                "format": "auto",
                "format.codec": "auto",
            },
        }
        execute(video_graph)
        # Disabled ports retain connections to guard nodes that fail if evaluated.
        reference = copy.deepcopy(video_graph)
        reference["2"]["class_type"] = "VividAIReferenceVideo"
        reference["2"]["inputs"].update(
            node_key=str(uuid.uuid4()),
            image_1=["4", 0],
            audio_1=["5", 0],
            video_1=["6", 0],
            image_9=["7", 0],
            model_rules=json.dumps(
                {
                    "mock-video-933": {
                        "max_audios": 0,
                        "max_videos": 0,
                        "max_images": 1,
                    }
                }
            ),
        )
        reference["4"] = {
            "class_type": "EmptyImage",
            "inputs": {
                "width": 64,
                "height": 64,
                "batch_size": 1,
                "color": 0,
            },
        }
        for index, kind in (("5", "Audio"), ("6", "Video"), ("7", "Image")):
            reference[index] = {"class_type": "VividAITestGuard" + kind, "inputs": {}}
        execute(reference)
        # An enabled reference port must also stay lazy in cached-output mode.
        reference["2"]["inputs"]["image_1"] = ["7", 0]
        execute(reference)
        # Exercise native VIDEO and AUDIO encoding, in reference-number order.
        mixed = copy.deepcopy(video_graph)
        mixed["2"]["class_type"] = "VividAIReferenceVideo"
        mixed["2"]["inputs"].update(
            node_key=str(uuid.uuid4()),
            image_1=["4", 0],
            video_1=["6", 0],
            audio_1=["5", 0],
        )
        mixed["4"] = copy.deepcopy(reference["4"])
        mixed["5"] = {
            "class_type": "EmptyAudio",
            "inputs": {
                "duration": 0.1,
                "sample_rate": 16000,
                "channels": 1,
            },
        }
        mixed["6"] = {"class_type": "CreateVideo", "inputs": {"images": ["4", 0], "fps": 24.0}}
        execute(mixed)
        stats = httpx.get("http://127.0.0.1:8200/__state").json()
        report = {
            "baseline": "ComfyUI 0.41.3 / frontend 1.55.17 / Windows / CPU",
            "submissions": stats["submissions"] - baseline["submissions"],
            "resumes": stats["resumes"] - baseline["resumes"],
            "uploads": stats["uploads"] - baseline["uploads"],
            "checks": [
                "IMAGE to SaveImage",
                "reuse after parameter/model edits",
                "explicit regeneration",
                "stream reconnect",
                "failure stops workflow",
                "manual history activation",
                "VIDEO to SaveVideo",
                "reference IMAGE/VIDEO/AUDIO uploads",
                "disabled-port lazy guards",
                "cached-output lazy guard",
            ],
        }
        assert report["submissions"] == 6 and report["resumes"] >= 1 and report["uploads"] == 4
        Path(".local/e2e-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
