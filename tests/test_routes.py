import asyncio
import sys
import uuid

from aiohttp import ClientSession, web

from vividai import routes, runtime
from vividai.storage import Store


def test_register_skips_when_comfy_server_is_not_loaded(monkeypatch):
    monkeypatch.delitem(sys.modules, "server", raising=False)

    assert routes.register() is False


def test_local_routes_redact_secrets_origin_guard_and_media_range(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(runtime, "_store", store)

    async def run():
        app = web.Application()
        app.add_routes(
            [
                web.get("/profiles", routes.profiles),
                web.post("/profiles", routes.save_profile),
                web.get("/nodes/{key}", routes.node_state),
                web.get("/nodes/{key}/media/{mid}", routes.media),
            ]
        )
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        try:
            async with ClientSession() as session:
                response = await session.post(
                    base + "/profiles",
                    json={
                        "name": "local",
                        "base": "https://vividai.run",
                        "secret": "vk_no_leak",
                    },
                )
                assert response.status == 200
                assert "vk_no_leak" not in await response.text()
                response = await session.get(base + "/profiles")
                assert "vk_no_leak" not in await response.text()
                response = await session.get(
                    base + "/profiles", headers={"Origin": "https://evil.test"}
                )
                assert response.status == 403
                response = await session.get(base + "/profiles", headers={"Host": "evil.test"})
                assert response.status == 403
                node = str(uuid.uuid4())
                store.begin(node, "initial", {}, "ref", "video")
                path = store.new_path(".mp4")
                path.write_bytes(b"0123456789")
                item = store.complete(node, "initial", path, {}, "video")
                response = await session.get(
                    f"{base}/nodes/{node}/media/{item['id']}",
                    headers={"Range": "bytes=2-4"},
                )
                assert response.status == 206
                assert await response.read() == b"234"
                assert store._leases[path.name] == 0
        finally:
            await runner.cleanup()

    asyncio.run(run())
