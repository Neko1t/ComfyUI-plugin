"""Loopback-only VividAI protocol simulator. Never calls the paid provider."""

import io
import json
import uuid

import av
import numpy as np
from aiohttp import web
from PIL import Image

jobs = {}
stats = {"submissions": 0, "resumes": 0, "uploads": 0}


async def models(request):
    return web.json_response({"data": [{"id": "mock-image"}, {"id": "mock-video-933"}]})


async def uploads(request):
    data = await request.json()
    key = f"refs/{data['kind']}/{uuid.uuid4()}"
    return web.json_response({"key": key, "url": f"{request.scheme}://{request.host}/put"})


async def put(request):
    assert "Authorization" not in request.headers
    await request.read()
    stats["uploads"] += 1
    return web.Response()


async def generate(request):
    data = await request.json()
    resumed = "jobId" in data
    if resumed:
        stats["resumes"] += 1
        job_id = data["jobId"]
        if set(data) != {"jobId"}:
            raise web.HTTPBadRequest()
    else:
        stats["submissions"] += 1
        job_id = str(uuid.uuid4())
        jobs[job_id] = data
    payload = jobs[job_id]
    stream = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await stream.prepare(request)
    await stream.write((json.dumps({"jobId": job_id, "status": "running"}) + "\n\n").encode())
    if "disconnect" in payload["prompt"] and not resumed:
        await stream.write_eof()
        return stream
    terminal = {
        "jobId": job_id,
        "status": "succeeded",
        "result": f"{request.scheme}://{request.host}/result/{job_id}",
    }
    if "fail" in payload["prompt"]:
        terminal = {"jobId": job_id, "status": "failed", "error": "mock explicit failure"}
    await stream.write((json.dumps(terminal) + "\n").encode())
    await stream.write_eof()
    return stream


async def result(request):
    assert "Authorization" not in request.headers
    job = jobs[request.match_info["job"]]
    buffer = io.BytesIO()
    if job["model"] == "mock-image":
        Image.new("RGB", (64, 64), "#618afa").save(buffer, format="PNG")
        return web.Response(body=buffer.getvalue(), content_type="image/png")
    with av.open(buffer, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        for _ in range(8):
            frame = av.VideoFrame.from_ndarray(
                np.full((64, 64, 3), 128, dtype=np.uint8), format="rgb24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return web.Response(body=buffer.getvalue(), content_type="video/mp4")


async def state(request):
    return web.json_response(stats | {"jobs": jobs})


if __name__ == "__main__":
    app = web.Application(client_max_size=45 * 1024**2)
    app.add_routes(
        [
            web.get("/v1/models", models),
            web.post("/v1/uploads", uploads),
            web.put("/put", put),
            web.post("/v1/generate", generate),
            web.get("/result/{job}", result),
            web.get("/__state", state),
        ]
    )
    web.run_app(app, host="127.0.0.1", port=8200, access_log=None)
