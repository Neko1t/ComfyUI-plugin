WEB_DIRECTORY = "./web"


async def comfy_entrypoint():
    from .vividai.nodes import VividAIExtension

    return VividAIExtension()
