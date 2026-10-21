import asyncio
import json

import httpx
import pytest
from aiohttp import web

from vividai.client import AmbiguousSubmission, Client, ProviderError, RemoteFailure, Upload

PROFILE = {"base": "https://api.test", "secret": "vk_do_not_leak"}


class BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"jobId":"original","status":"running"}\n\n'
        raise httpx.ReadError("broken")


def test_reconnect_only_job_id_and_immediate_persistence():
    requests, saved = [], []

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, stream=BrokenStream())
        assert saved == ["original"]
        return httpx.Response(
            200,
            text=json.dumps(
                {
                    "jobId": "original",
                    "status": "succeeded",
                    "result": "https://cdn.test/x",
                }
            )
            + "\n",
        )

    async def run():
        async with Client(PROFILE, transport=httpx.MockTransport(handler)) as client:
            result = await client.generate({"model": "any"}, job_id=None, on_job=saved.append)
            assert result["status"] == "succeeded"

    asyncio.run(run())
    assert requests == [{"model": "any"}, {"jobId": "original"}]


def test_no_blind_retry_or_secret_in_failure():
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadError("unknown acceptance")

    async def run():
        async with Client(PROFILE, transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AmbiguousSubmission):
                await client.generate({}, job_id=None, on_job=lambda _: None)

    asyncio.run(run())
    assert count == 1

    async def failed(request):
        return httpx.Response(
            200,
            text=json.dumps(
                {
                    "jobId": "x",
                    "status": "failed",
                    "error": PROFILE["secret"],
                }
            ),
        )

    async def check_failure():
        async with Client(PROFILE, transport=httpx.MockTransport(failed)) as client:
            with pytest.raises(RemoteFailure) as error:
                await client.generate({}, job_id="x", on_job=lambda _: None)
            assert PROFILE["secret"] not in str(error.value)

    asyncio.run(check_failure())


def test_models_accept_documented_top_level_array_and_legacy_data_wrapper():
    catalog = [
        {"id": "image-new", "kind": "image", "qualities": ["1K", "4K"], "refImages": 4},
        {
            "id": "video-900",
            "kind": "video",
            "qualities": ["480p", "720p"],
            "duration": {"mode": "range", "min": 4, "max": 15},
            "refImages": 9,
            "refVideos": 3,
            "refAudios": 3,
        },
    ]

    async def run(body):
        async def handler(request):
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json=body)

        async with Client(PROFILE, transport=httpx.MockTransport(handler)) as client:
            return await client.models()

    assert asyncio.run(run(catalog)) == catalog
    assert asyncio.run(run({"data": catalog})) == catalog
    with pytest.raises(ProviderError, match="模型列表响应格式不正确"):
        asyncio.run(run({"models": catalog}))


def test_real_http_upload_ndjson_download(tmp_path):
    """Real loopback sockets exercise streaming and credential separation."""
    seen = []

    async def run():
        async def models(request):
            assert request.headers["Authorization"] == "Bearer vk_test"
            return web.json_response(
                [
                    {"id": "renamable-933", "kind": "video", "qualities": ["720p"]},
                    {"id": "image-new", "kind": "image", "qualities": ["1K"]},
                ]
            )

        async def upload(request):
            assert await request.json() == {"kind": "image", "mime": "image/png"}
            return web.json_response({"key": "owned/image", "url": f"{base}/put"})

        async def put(request):
            assert "Authorization" not in request.headers
            assert request.content_type == "image/png"
            assert await request.read() == b"png-binary"
            seen.append("put")
            return web.Response(status=200)

        async def generate(request):
            assert (await request.json())["refs"] == ["owned/image"]
            stream = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
            await stream.prepare(request)
            await stream.write(b'{"jobId":"live-job","status":"running"}\n\n')
            await stream.write(
                (
                    json.dumps(
                        {
                            "jobId": "live-job",
                            "status": "succeeded",
                            "result": f"{base}/result",
                        }
                    )
                    + "\n"
                ).encode()
            )
            await stream.write_eof()
            return stream

        async def result(request):
            assert "Authorization" not in request.headers
            return web.Response(body=b"generated-result")

        app = web.Application()
        app.add_routes(
            [
                web.get("/v1/models", models),
                web.post("/v1/uploads", upload),
                web.put("/put", put),
                web.post("/v1/generate", generate),
                web.get("/result", result),
            ]
        )
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        try:
            async with Client({"base": base, "secret": "vk_test"}) as client:
                assert [x["id"] for x in await client.models()] == ["renamable-933", "image-new"]
                ref = await client.upload(Upload("image", "image/png", b"png-binary"))
                event = await client.generate({"refs": [ref]}, job_id=None, on_job=seen.append)
                await client.download(event["result"], tmp_path / "result.png")
                assert (tmp_path / "result.png").read_bytes() == b"generated-result"
        finally:
            await runner.cleanup()

    asyncio.run(run())
    assert seen == ["put", "live-job"]
