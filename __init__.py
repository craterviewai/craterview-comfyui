"""CraterView.ai nodes for ComfyUI. ComfyUI loads this file and calls `comfy_entrypoint`."""

from .craterview_comfyui.nodes import comfy_entrypoint

__all__ = ["comfy_entrypoint"]
