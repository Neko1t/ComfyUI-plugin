"""Conversions to/from ComfyUI native types. Host torch is imported only when needed."""

from __future__ import annotations

import io
import wave
import weakref
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageOps

from .client import Upload


def encode(kind: str, value) -> Upload:
    buffer = io.BytesIO()
    if kind == "image":
        if value.ndim != 4 or value.shape[0] != 1:
            raise ValueError("每个图片端口只接受一张 IMAGE，不接受批次")
        pixels = (value[0].detach().cpu().float().numpy().clip(0, 1) * 255).astype(np.uint8)
        Image.fromarray(pixels).save(buffer, format="PNG")
        return Upload(kind, "image/png", buffer.getvalue())
    if kind == "video":
        from comfy_api.latest import Types

        value.save_to(buffer, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
        return Upload(kind, "video/mp4", buffer.getvalue())
    waveform = value["waveform"]
    if waveform.ndim != 3 or waveform.shape[0] != 1 or waveform.shape[1] not in {1, 2}:
        raise ValueError("每个音频端口只接受一份单声道或双声道 AUDIO")
    samples = waveform[0].detach().cpu().float().numpy().clip(-1, 1).T
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(int(value["sample_rate"]))
        stream.writeframes((samples * 32767).astype("<i2").tobytes())
    return Upload("audio", "audio/wav", buffer.getvalue())


def validate_result(path: Path, kind: str):
    if kind == "image":
        # Normalize the actual format to PNG; URL suffix/Content-Type can be wrong.
        with Image.open(path) as source:
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("文生图接口返回了多帧素材，首版只支持单张图片")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
        image.save(path, format="PNG")
        return
    with av.open(str(path)) as container:
        if not container.streams.video or next(container.decode(video=0), None) is None:
            raise ValueError("结果没有可解码的视频帧")


def native_output(store, material):
    if material["kind"] == "image":
        import torch

        with store.lease(material["file"]) as path, Image.open(path) as image:
            pixels = np.array(image.convert("RGB"), dtype=np.float32) / 255
        return torch.from_numpy(pixels)[None, ...]
    from comfy_api.latest import InputImpl

    path, release = store.acquire(material["file"])
    try:
        video = InputImpl.VideoFromFile(str(path))
        weakref.finalize(video, release)
        return video
    except BaseException:
        release()
        raise
