"""The nodes: one class per model the catalogue offers, built when ComfyUI loads the pack."""

from __future__ import annotations

from pathlib import Path

import comfy.model_management
import comfy.utils
import folder_paths
from comfy_api.latest import ComfyExtension, io
from server import PromptServer

from . import core

CATEGORY = "CraterView.ai"
NUMBER_STEP = 0.01


def _home() -> Path:
    # Folders under `user` that start with `__` are ones ComfyUI will not serve over HTTP. The
    # ordinary `user/default` is readable by anything that can reach the server.
    return Path(folder_paths.get_user_directory()) / "__craterview"


def _input(setting: core.Setting) -> io.Input:
    # Optional, because the inputs follow the catalogue: a workflow saved as JSON and run by a
    # script still validates after a model gains a setting.
    shared = {"optional": True, "tooltip": setting.tooltip, "default": setting.start}
    if setting.kind == "choice":
        return io.Combo.Input(setting.name, options=list(setting.options), **shared)
    if setting.kind == "toggle":
        return io.Boolean.Input(setting.name, **shared)
    if setting.kind == "text":
        return io.String.Input(setting.name, multiline=True, **shared)
    if setting.kind == "integer":
        # ComfyUI gives an input named `seed` a control that changes it after every run unless
        # told not to. Each change starts a new job, which is charged.
        return io.Int.Input(setting.name, min=setting.lowest, max=setting.highest, step=1,
                            control_after_generate=False, **shared)
    return io.Float.Input(setting.name, min=setting.lowest, max=setting.highest, step=NUMBER_STEP,
                          **shared)


def node_for(model: dict) -> type[io.ComfyNode]:
    model_settings = core.settings(model)

    class CraterViewNode(io.ComfyNode):
        @classmethod
        def define_schema(cls) -> io.Schema:
            return io.Schema(
                node_id=model["id"],
                display_name=f"CraterView.ai {model['title']}",
                category=CATEGORY,
                description=f"{model.get('help', '')} Each image in a batch is a job of its own.",
                inputs=[io.Image.Input("image"), *map(_input, model_settings)],
                outputs=[io.Image.Output()],
                hidden=[io.Hidden.unique_id],
                is_deprecated=model.get("retired", False),
            )

        @classmethod
        def GET_NODE_INFO_V1(cls) -> dict:
            # The inputs follow the catalogue, so a model that gains a setting moves the ones after
            # it, and a saved workflow restored by position would give each the wrong value. With
            # this list ComfyUI's frontend restores a saved workflow's settings by name.
            return {**super().GET_NODE_INFO_V1(),
                    "fallbackWidgetsValuesNames": [setting.name for setting in model_settings]}

        @classmethod
        def execute(cls, image, **values) -> io.NodeOutput:
            # Here and not in `validate_inputs`, which would stop a long workflow sooner. ComfyUI's
            # notice for that says "rejected the value for unknown input" and shows these words
            # only in the log. An error raised here is under View details.
            key = core.api_key(_home())
            if not key:
                raise core.CraterViewError(core.no_key(_home()))

            bar = comfy.utils.ProgressBar(100)
            node = cls.hidden.unique_id

            def report(text: str, fraction: float) -> None:
                bar.update_absolute(round(fraction * 100))
                PromptServer.instance.send_progress_text(text, node)

            results = core.run_batch(
                core.client_for(key), model["id"], image.cpu().numpy(),
                core.chosen(model_settings, values),
                comfy.model_management.throw_exception_if_processing_interrupted, report)
            return io.NodeOutput(image.new_tensor(results))

    return CraterViewNode


class CraterViewExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [node_for(model) for model in core.load_models(_home())]


async def comfy_entrypoint() -> CraterViewExtension:
    return CraterViewExtension()
