from __future__ import annotations

from comfy_api.latest import ComfyExtension, io

from . import runtime
from .media import native_output
from .rules import model_rule, normalize_prompt, ports

CONFIG = io.Custom("VIVIDAI_CONFIG")
OPENAI_CONTENT = io.Custom("OPENAI_CONTENT")


class VividAIConfig(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="VividAIConfig",
            display_name="VividAI 配置",
            category="VividAI",
            inputs=[
                io.String.Input("config_ref", default="", tooltip="本机配置引用，不保存 API Key")
            ],
            outputs=[CONFIG.Output(display_name="配置")],
        )

    @classmethod
    def execute(cls, config_ref):
        runtime.store().profile(config_ref)
        return io.NodeOutput(config_ref)


class Generation(io.ComfyNode):
    KIND = "video"
    REFERENCES = False
    NODE_ID = ""
    TITLE = ""

    @classmethod
    def define_schema(cls):
        inputs = [
            CONFIG.Input("config", lazy=True),
            io.String.Input("model", default=""),
            io.MultiType.Input(
                io.String.Input("prompt", default="", multiline=True),
                types=[OPENAI_CONTENT],
                tooltip="支持普通文本，也支持 OpenAI messages/input 内容对象",
            ),
            io.String.Input("quality", default="1K" if cls.KIND == "image" else "720p"),
            io.String.Input("ratio", default="1:1" if cls.KIND == "image" else "16:9"),
            io.Int.Input(
                "duration", default=0, min=0, max=3600, tooltip="0 表示不提交时长；模型要求时需填写"
            ),
            io.Int.Input("history_capacity", default=3, min=1, max=100),
            io.String.Input("node_key", default=""),
            io.String.Input("generation_token", default=""),
            io.String.Input("model_rules", default="{}"),
        ]
        if cls.REFERENCES:
            for kind, type_, bound in (
                ("image", io.Image, 9),
                ("video", io.Video, 3),
                ("audio", io.Audio, 3),
            ):
                inputs.extend(
                    type_.Input(f"{kind}_{i}", optional=True, lazy=True)
                    for i in range(1, bound + 1)
                )
        return io.Schema(
            node_id=cls.NODE_ID,
            display_name=cls.TITLE,
            category="VividAI",
            inputs=inputs,
            outputs=[io.Image.Output() if cls.KIND == "image" else io.Video.Output()],
            description="默认复用选中素材。参数修改只在显式标记下次重新生成后生效。",
            not_idempotent=True,
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        # The persistent state, including history activation, is authoritative. Always visit it.
        return float("nan")

    @classmethod
    def check_lazy_status(cls, node_key, generation_token="", model="", model_rules="{}", **kwargs):
        action, _ = runtime.service().decision(node_key, generation_token)
        if action != "new":
            return []
        needed = ["config"] if kwargs.get("config") is None else []
        if cls.REFERENCES:
            needed.extend(
                name
                for name in ports(model_rule(model_rules, model))
                if name in kwargs and kwargs[name] is None
            )
        return needed

    @classmethod
    async def execute(
        cls,
        node_key,
        model,
        prompt,
        quality,
        ratio,
        duration,
        history_capacity=3,
        model_rules="{}",
        generation_token="",
        config=None,
        **kwargs,
    ):
        import comfy.model_management

        # Do not validate modified model rules while reusing an existing output.
        action, _ = runtime.service().decision(node_key, generation_token)
        rule = model_rule(model_rules, model) if action == "new" else {}
        references = {
            name: kwargs[name]
            for name in (ports(rule) if cls.REFERENCES and rule else [])
            if kwargs.get(name) is not None
        }
        snapshot = {
            "model": model,
            "prompt": normalize_prompt(prompt),
            "quality": quality,
            "ratio": ratio,
            "duration": duration,
            "kind": cls.KIND,
            "rule": rule,
        }
        material = await runtime.service().run(
            node_key,
            generation_token,
            config,
            snapshot,
            references,
            history_capacity,
            interrupt=comfy.model_management.throw_exception_if_processing_interrupted,
        )
        output = native_output(runtime.store(), material)
        return io.NodeOutput(output, ui={"vividai": [{"node_key": node_key}]})


class VividAITextToImage(Generation):
    KIND, NODE_ID, TITLE = "image", "VividAITextToImage", "VividAI 文生图"


class VividAITextToVideo(Generation):
    NODE_ID, TITLE = "VividAITextToVideo", "VividAI 文生视频"


class VividAIReferenceVideo(Generation):
    REFERENCES = True
    NODE_ID, TITLE = "VividAIReferenceVideo", "VividAI 参考素材生视频"


class VividAIExtension(ComfyExtension):
    async def on_load(self):
        from .routes import register

        register()

    async def get_node_list(self):
        return [VividAIConfig, VividAITextToImage, VividAITextToVideo, VividAIReferenceVideo]
