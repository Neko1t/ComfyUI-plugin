"""Single-user local UI routes. Secrets are accepted separately from workflow parameters."""

from __future__ import annotations

import ipaddress
import sys
from functools import wraps
from urllib.parse import urlsplit

from aiohttp import web

from . import runtime
from .client import Client, ProviderError

_registered_server = None


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def local_only(handler):
    @wraps(handler)
    async def wrapped(request):
        host = urlsplit(f"{request.scheme}://{request.host}")
        if not _loopback(request.remote) or not _loopback(host.hostname):
            raise web.HTTPForbidden(text="VividAI 本机管理界面仅允许 localhost 访问")
        origin = request.headers.get("Origin")
        if (origin and origin.rstrip("/") != f"{request.scheme}://{request.host}") or (
            request.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            raise web.HTTPForbidden(text="VividAI 拒绝跨来源访问")
        try:
            return await handler(request)
        except (ValueError, ProviderError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except web.HTTPException:
            raise
        except Exception:
            return web.json_response({"error": "本机操作失败，请检查连接和配置"}, status=500)

    return wrapped


@local_only
async def profiles(request):
    return web.json_response({"profiles": runtime.store().profiles()})


@local_only
async def save_profile(request):
    data = await request.json()
    ref = runtime.store().save_profile(
        data.get("name", ""),
        data.get("base", "https://vividai.run"),
        data.get("secret", ""),
        data.get("id"),
    )
    return web.json_response({"id": ref})


@local_only
async def delete_profile(request):
    runtime.store().delete_profile(request.match_info["ref"])
    return web.json_response({"ok": True})


@local_only
async def models(request):
    profile = runtime.store().profile(request.query.get("config_ref", ""))
    async with Client(profile) as client:
        values = await client.models()
    return web.json_response({"models": values})


@local_only
async def node_state(request):
    return web.json_response(runtime.store().public_node(request.match_info["key"]))


@local_only
async def activate(request):
    data = await request.json()
    runtime.store().activate(request.match_info["key"], data["material_id"])
    return web.json_response(runtime.store().public_node(request.match_info["key"]))


class LeasedFileResponse(web.FileResponse):
    def __init__(self, path, release):
        super().__init__(path, headers={"Cache-Control": "private, no-store"})
        self._release = release

    async def prepare(self, request):
        try:
            return await super().prepare(request)
        finally:
            self._release()


@local_only
async def media(request):
    store = runtime.store()
    node = store.node(request.match_info["key"])
    material = next((x for x in node["history"] if x["id"] == request.match_info["mid"]), None)
    if material is None:
        raise web.HTTPNotFound()
    path, release = store.acquire(material["file"])
    if not path.is_file():
        release()
        raise web.HTTPNotFound()
    return LeasedFileResponse(path, release)


def register():
    global _registered_server

    # Registry and other discovery tools may load the extension without a
    # running ComfyUI server. Importing server in that context initializes
    # the full runtime (including the GPU backend) and prevents node schema
    # discovery. ComfyUI has already imported server before loading custom
    # nodes, so only register routes when that module is ready.
    server_module = sys.modules.get("server")
    if server_module is None:
        return False

    PromptServer = getattr(server_module, "PromptServer", None)
    if PromptServer is None or getattr(PromptServer, "instance", None) is None:
        return False

    server_instance = PromptServer.instance
    if _registered_server is server_instance:
        return True

    routes = server_instance.routes
    for method, path, handler in (
        ("GET", "/vividai/profiles", profiles),
        ("POST", "/vividai/profiles", save_profile),
        ("DELETE", "/vividai/profiles/{ref}", delete_profile),
        ("GET", "/vividai/models", models),
        ("GET", "/vividai/nodes/{key}", node_state),
        ("POST", "/vividai/nodes/{key}/activate", activate),
        ("GET", "/vividai/nodes/{key}/media/{mid}", media),
    ):
        routes.route(method, path)(handler)
    _registered_server = server_instance
    return True
