"""Test-only guard nodes; install ONLY in the isolated integration ComfyUI instance."""

from comfy_api.latest import ComfyExtension, io


class Guard(io.ComfyNode):
    NAME = ""
    TYPE = io.Image

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id=cls.NAME, category="VividAI test only", outputs=[cls.TYPE.Output()]
        )

    @classmethod
    def execute(cls):
        raise AssertionError("Lazy guard was evaluated: " + cls.NAME)


class GuardImage(Guard):
    NAME = "VividAITestGuardImage"


class GuardVideo(Guard):
    NAME, TYPE = "VividAITestGuardVideo", io.Video


class GuardAudio(Guard):
    NAME, TYPE = "VividAITestGuardAudio", io.Audio


class TestExtension(ComfyExtension):
    async def get_node_list(self):
        return [GuardImage, GuardVideo, GuardAudio]


async def comfy_entrypoint():
    return TestExtension()
