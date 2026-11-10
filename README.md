# CraterView.ai nodes for ComfyUI

Use [CraterView.ai](https://craterview.ai)'s photo tools as nodes in a ComfyUI workflow. Each
node takes an image and returns an image. The work runs on CraterView.ai's servers, so you need
no graphics card and no model files.

The nodes are built from the [catalogue](https://api.craterview.ai/v1/models) when ComfyUI
starts, so a new model or setting appears after a restart, with no update to the pack:

- [Enhance](https://craterview.ai/features/enhance) makes a photo larger and sharper.
- [Denoise](https://craterview.ai/features/denoise) takes the grain out of a low-light photo.
- [Restore](https://craterview.ai/features/restore) repairs tears, creases and faded colour.
- [Small face enhancement](https://craterview.ai/features/small-faces) fixes small, blurry faces
  in a group photo.
- [Headshot](https://craterview.ai/features/headshot) turns a photo of a face into a
  professional headshot.

The nodes are in the **CraterView.ai** category. Prices and limits are on each model's page.

Run Enhance on the original photograph, before Denoise or Restore. It might not work well on
another model's result.

## Install

**In ComfyUI Manager**, search for CraterView.ai, install it and restart ComfyUI.

**With comfy-cli:**

```bash
comfy node install craterview
```

**By hand:**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/craterviewai/craterview-comfyui
pip install -r craterview-comfyui/requirements.txt
```

## Add your API key

Get a key from your [dashboard](https://craterview.ai/dashboard). Then do one of these:

- **Set a variable** where ComfyUI starts, then restart it:

  ```bash
  export CV_API_KEY=cv_...
  ```

- **Save it in a file**, which needs no restart. Put the key in
  `ComfyUI/user/__craterview/api_key.txt`, creating the folder if it is not there.
  ComfyUI does not serve that folder over its web interface. If your ComfyUI keeps its folders
  somewhere else, run a node with no key: its error, under View details, names the exact path.

**Never type the key into a node.** ComfyUI saves every node input in each PNG it writes, so the
key would go with every image you share. These nodes have no input for it, and saved images and
workflows do not contain it.

## In the cloud

| Where ComfyUI runs | Install the pack | Add the key |
|---|---|---|
| A rented GPU server | ComfyUI Manager, or by hand | Set `CV_API_KEY` in the server's environment settings |
| Your own Docker image or serverless worker | `git clone` and `pip install` in the Dockerfile | Pass `CV_API_KEY` as a secret when it starts, and never build it into the image |
| A hosted ComfyUI site that lets you add nodes | ComfyUI Manager | The site's environment settings, or the key file if it has a file browser |
| Comfy Cloud | Not available yet: Comfy Cloud runs only the nodes Comfy has installed | |

These nodes need no graphics card of their own, so ComfyUI can run on a small server, as long
as it can reach `api.craterview.ai` and storage for uploads and results.

In ComfyUI 0.44 and later, a saved workflow keeps its settings when a model gains a new one. A
workflow saved in API format keeps working too, because every setting is optional.

## How a node behaves

- **Each image in a batch is a job of its own.** A batch of 16 is 16 jobs, each priced as one.
- **Without credit or a subscription, a job runs free** on the community queue: the same models,
  with smaller size limits and longer waits at busy times.
- **Running again with nothing changed starts no job.** ComfyUI reuses the result. Changing
  anything before the node starts a new job, and so does restarting ComfyUI.
- **Stop does not cancel a job.** It stops ComfyUI waiting. The job carries on and is charged if
  it succeeds, and the log names it.
- **A setting left at its starting value is not sent,** so the model's own default applies. To set
  a result's size, change one of `scale`, `width` or `height`. Changing two is refused.
- **To work on part of an image, crop it first** with an image node.
- **If ComfyUI starts with no network,** it uses the last model list it read. On a first start with
  no network, the nodes load the next time it starts with one.
- **Images leave your machine.** See the [privacy policy](https://craterview.ai/privacy) for what
  is stored and for how long.

## Licence

GPL-3.0, the same as ComfyUI, whose node API this pack imports. The
[`craterview`](https://pypi.org/project/craterview/) client it uses is Apache-2.0.
