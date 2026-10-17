try:
    from .vividai.nodes import (
        VividAIConfig,
        VividAIExtension,
        VividAIReferenceVideo,
        VividAITextToImage,
        VividAITextToVideo,
    )
    from .vividai.routes import register
except ImportError:
    # Pytest and ComfyUI's file-based loader can execute this file without a
    # package parent. Keep the same static class references in that mode.
    from vividai.nodes import (
        VividAIConfig,
        VividAIExtension,
        VividAIReferenceVideo,
        VividAITextToImage,
        VividAITextToVideo,
    )
    from vividai.routes import register

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "VividAIConfig": VividAIConfig,
    "VividAITextToImage": VividAITextToImage,
    "VividAITextToVideo": VividAITextToVideo,
    "VividAIReferenceVideo": VividAIReferenceVideo,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "VividAIConfig": "VividAI 配置",
    "VividAITextToImage": "VividAI 文生图",
    "VividAITextToVideo": "VividAI 文生视频",
    "VividAIReferenceVideo": "VividAI 参考素材生视频",
}

# ComfyUI loads NODE_CLASS_MAPPINGS before comfy_entrypoint, so V3 on_load
# is skipped when both interfaces are exported.
register()


async def comfy_entrypoint():
    return VividAIExtension()
