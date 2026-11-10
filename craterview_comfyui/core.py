"""What the nodes do, apart from ComfyUI: which models get a node, which of a model's settings
become inputs, and how a picture becomes a job and comes back.

Nothing here imports ComfyUI, so all of it can be tested without one. `nodes.py` is the rest.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import numpy as np
from craterview import (ConnectionFailed, CraterView, CraterViewError, Job, JobFailed, RateLimited,
                        TimedOut, new_idempotency_key)
from PIL import Image

KEY_VARIABLE = "CV_API_KEY"
KEY_FILE = "api_key.txt"
CATALOG_FILE = "catalog.json"
KEY_PAGE = "https://craterview.ai/dashboard"

# ComfyUI waits for this at startup, so a network that drops packets costs seconds, not minutes.
CATALOG_TIMEOUT_SECONDS = 10.0
POLL_SECONDS = 1.0
RETRY_SECONDS = 2.0

# The number a person may type where the catalogue sets no upper limit. ComfyUI's widgets stop at
# 2048 when told nothing, which is smaller than many results.
LARGEST = 2_147_483_647

# How the result file is written. A node decodes that file straight into an image, so these have
# nothing to do: a PNG goes up, and the default sends a PNG back, with nothing lost on the way.
FILE_SETTINGS = frozenset({"output_format", "quality"})

Stop = Callable[[], None]
Report = Callable[[str, float], None]


# ---------------------------------------------------------------------- the catalogue


def offered(models: list[dict]) -> list[dict]:
    """The models that get a node: in service, taking a picture and giving a picture back."""
    return [m for m in models
            if not m.get("coming_soon") and not m.get("test_model")
            and (m.get("produces") or "").startswith("image/")
            and any(kind.startswith("image/") for kind in m.get("accepts", []))]


def load_models(home: Path, client: CraterView | None = None) -> list[dict]:
    """The models to build nodes from: the catalogue as it stands, read without a key.

    ComfyUI asks for a pack's nodes once, at startup. A saved copy covers the two cases where the
    catalogue alone would leave a saved workflow with missing nodes: a start with no network, and
    a model no longer listed but still served, which stays as a node marked `retired`.
    """
    cache = home / CATALOG_FILE
    saved = _read_saved(cache)
    try:
        listed = offered((client or CraterView(timeout=CATALOG_TIMEOUT_SECONDS)).models())
    except CraterViewError as failure:
        logging.warning("CraterView.ai: could not read the model list (%s). %s", failure,
                        "Using the saved list." if saved else
                        "Its nodes will load the next time ComfyUI starts with a network.")
        return saved
    names = {model["id"] for model in listed}
    models = listed + [{**model, "retired": True} for model in saved if model["id"] not in names]
    _write_saved(cache, models)
    return models


def _read_saved(cache: Path) -> list[dict]:
    try:
        return json.loads(cache.read_text())
    except (OSError, ValueError):
        return []


def _write_saved(cache: Path, models: list[dict]) -> None:
    """Saved beside nothing that matters: a read-only image only gives up the saved copy. Written
    to a second file first, because two servers can share one volume."""
    written = cache.with_name(f"{cache.name}.{os.getpid()}")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(json.dumps(models))
        os.replace(written, cache)
    except OSError as failure:
        logging.info("CraterView.ai: could not save the model list: %s", failure)


# ------------------------------------------------------------------------ the settings


@dataclass(frozen=True)
class Setting:
    """One input on a node. `start` is the value it starts at, and left there it is not sent."""

    name: str
    kind: str  # "choice", "toggle", "text", "integer" or "number"
    start: Any
    tooltip: str | None = None
    options: tuple[str, ...] = ()
    lowest: float | None = None
    highest: float | None = None


def settings(model: dict) -> list[Setting]:
    """A model's settings that make one input each, in the catalogue's order.

    The catalogue can gain a shape this release has never seen, and it is read at startup, so a
    shape with no input is left out rather than failing the node. A region, an object of four
    numbers, is one of those today: crop the image first with an image node.
    """
    properties = (model.get("params_schema") or {}).get("properties") or {}
    notes = model.get("params_help") or {}
    found = (_setting(name, properties[name], notes.get(name))
             for name in model.get("params_order") or properties
             if name in properties and name not in FILE_SETTINGS)
    return [setting for setting in found if setting]


def _setting(name: str, spec: dict, note: str | None) -> Setting | None:
    default = spec.get("default")
    if "enum" in spec:
        options = spec["enum"]
        if default in options and all(isinstance(option, str) for option in options):
            return Setting(name, "choice", default, note, options=tuple(options))
        return None
    kind = spec.get("type")
    if kind == "boolean":
        return Setting(name, "toggle", default, note) if isinstance(default, bool) else None
    if kind == "string":
        return Setting(name, "text", default or "", note)
    if kind not in ("integer", "number"):
        return None
    lowest, highest = spec.get("minimum"), spec.get("maximum", LARGEST)
    if default is not None:
        return Setting(name, kind, default, note, lowest=lowest, highest=highest)
    if lowest is None:
        return None
    # A number that may be left out has no value meaning "left out", so it gets one, just below
    # the numbers the API takes.
    start = lowest - 1
    said = f"{note} " if note else ""
    return Setting(name, kind, start, f"{said}{start} leaves it unset.", lowest=start,
                   highest=highest)


def chosen(model_settings: list[Setting], values: dict) -> dict:
    """What to send: what the person changed, and nothing else.

    A widget always holds a value, and the API refuses some settings together: a scale with a
    width, say. Sending only what was changed asks for what was meant, and leaves the API's own
    default on the rest, including a default that depends on another setting.
    """
    return {setting.name: values[setting.name] for setting in model_settings
            if values.get(setting.name, setting.start) != setting.start}


# ----------------------------------------------------------------------------- the key


def api_key(home: Path) -> str | None:
    """The key, from the environment or from a file in ComfyUI's user folder.

    Never a node input: ComfyUI writes every input into each PNG it saves, so a key in a node
    leaves with every image someone shares. The file is for where setting a variable is awkward:
    ComfyUI started from an icon, or a hosted server with a file browser and no settings for it.
    """
    key = os.environ.get(KEY_VARIABLE, "").strip()
    if key:
        return key
    try:
        return (home / KEY_FILE).read_text().strip() or None
    except OSError:
        return None


def no_key(home: Path) -> str:
    return (f"CraterView.ai needs an API key. Get one at {KEY_PAGE}. Then save it in "
            f"{home / KEY_FILE}, or set {KEY_VARIABLE} and restart ComfyUI.")


def client_for(key: str | None, **options: Any) -> CraterView:
    client = CraterView(api_key=key, **options)
    # Which requests came from a workflow is the only measure of whether anyone uses this pack.
    client._session.headers["User-Agent"] += " craterview-comfyui"
    return client


# ---------------------------------------------------------------------------- the pictures


def encode(frame: np.ndarray) -> bytes:
    """One image of a batch, as ComfyUI holds it — floats from 0 to 1 — as a PNG."""
    pixels = np.clip(np.round(frame * 255.0), 0, 255).astype(np.uint8)
    written = BytesIO()
    Image.fromarray(pixels[..., 0] if pixels.shape[-1] == 1 else pixels).save(written, "PNG")
    return written.getvalue()


def decode(data: bytes) -> np.ndarray:
    """A result, as ComfyUI holds an image. ComfyUI's images have no alpha channel."""
    with Image.open(BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


# ----------------------------------------------------------------------------- the job


def _only_a_wait(failure: CraterViewError) -> bool:
    """No answer, a failure on the way to the API, or a request to slow down. None of these says
    anything about the job. A refusal is the same answer the next time."""
    return isinstance(failure, (TimedOut, ConnectionFailed, RateLimited)) \
        or (failure.status or 0) >= 500


def _pause(seconds: float, stop: Stop) -> None:
    deadline = time.monotonic() + seconds
    while True:
        stop()
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.25))


def _asked(call: Callable[[], Any], stop: Stop, report: Report, fraction: float) -> Any:
    """`call`'s answer. A limit is waited out for as long as it holds, however long the person
    lets it. Any other failure worth repeating is asked once more."""
    asked_again = False
    while True:
        try:
            return call()
        except RateLimited as failure:
            report(f"Waiting: {failure}", fraction)
            _pause(max(failure.retry_after or 0, POLL_SECONDS), stop)
        except CraterViewError as failure:
            if asked_again or not _only_a_wait(failure):
                raise
            asked_again = True
            _pause(RETRY_SECONDS, stop)


def _progress(job: Job) -> tuple[str, float]:
    said = job.status
    if job.eta_seconds is not None:
        said += f", about {round(job.eta_seconds)} s"
    return said, (job.progress or {}).get("fraction") or 0.0


def _settled(client: CraterView, job: Job, stop: Stop, report: Report) -> Job:
    """The job once it finishes. The API has no cancel, so stopping here stops only the wait,
    which is the one thing a person pressing Stop has to be told."""
    try:
        while not job.done:
            report(*_progress(job))
            _pause(POLL_SECONDS, stop)
            try:
                job = client.job(job.id)
            except CraterViewError as failure:
                if not _only_a_wait(failure):
                    raise
    except BaseException:  # ComfyUI's stop is not an Exception
        logging.warning("CraterView.ai: stopped waiting for job %s. It carries on, and is charged "
                        "if it succeeds.", job.id)
        raise
    return job


def run_frame(client: CraterView, model: str, png: bytes, params: dict, stop: Stop,
              report: Report) -> bytes:
    """One PNG through one job, and the result's bytes."""
    report("Uploading", 0.0)
    upload = _asked(lambda: client.upload(png, "image/png"), stop, report, 0.0)
    # One key for every attempt, so asking again can never start a second job.
    key = new_idempotency_key()
    job = _asked(lambda: client.submit(model, upload, idempotency_key=key, **params),
                 stop, report, 0.0)
    logging.info("CraterView.ai: %s job %s submitted", model, job.id)
    job = _settled(client, job, stop, report)
    if not job.succeeded:
        raise JobFailed(f"{model} job {job.id} failed: {job.error or 'no reason was given'}",
                        job.error_code, job.id)
    logging.info("CraterView.ai: job %s finished, %s credits", job.id, job.credits)
    report("Downloading", 1.0)
    return _asked(job.bytes, stop, report, 1.0)


def run_batch(client: CraterView, model: str, frames: np.ndarray, params: dict, stop: Stop,
              report: Report) -> np.ndarray:
    """Every image of a batch through a job of its own, one after another."""
    total = len(frames)
    results = []
    for index, frame in enumerate(frames):
        def said(text: str, fraction: float) -> None:
            report(f"Image {index + 1} of {total}: {text}", (index + fraction) / total)

        results.append(decode(run_frame(client, model, encode(frame), params, stop, said)))
    return np.stack(results)
