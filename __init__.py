from importlib import import_module

WEB_DIRECTORY = "./web"

_module_prefix = f"{__package__}." if __package__ else ""
_nodes = import_module(f"{_module_prefix}vividai.nodes")
_register_routes = import_module(f"{_module_prefix}vividai.routes").register

NODE_CLASS_MAPPINGS = {
    "VividAIConfig": _nodes.VividAIConfig,
    "VividAITextToImage": _nodes.VividAITextToImage,
    "VividAITextToVideo": _nodes.VividAITextToVideo,
    "VividAIReferenceVideo": _nodes.VividAIReferenceVideo,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    node_id: node_class.define_schema().display_name
    for node_id, node_class in NODE_CLASS_MAPPINGS.items()
}

# ComfyUI loads NODE_CLASS_MAPPINGS before comfy_entrypoint, so V3 on_load
# is skipped when both interfaces are exported.
_register_routes()


async def comfy_entrypoint():
    return _nodes.VividAIExtension()
