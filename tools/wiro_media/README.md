# Wiro AI Media

Generate images, videos, speech and music in Dify workflows, chatflows and agents with models on Wiro AI, or run any of its 1,000+ models by ID. One Wiro AI API key covers all of them, and the results come back to Dify as files.

## Tools

| Tool | What it does | Default model |
| --- | --- | --- |
| Generate Image | Creates an image from a prompt, or edits the input images | `google/nano-banana-2` |
| Generate Video | Creates a video from a prompt, a start image or both | `bytedance/seedance-v1-pro-fast` |
| Text to Speech | Reads text aloud in the chosen voice | `elevenlabs/eleven-v4` |
| Generate Music | Creates music or sound effects from a description | `elevenlabs/text-to-music-v2` |
| Run Any Model | Runs any Wiro AI model by ID with its own parameters | none |
| Get Task Result | Collects the files of a task that was still running | none |
| Search Models | Finds models by name and task | none |
| Get Model Parameters | Lists a model's parameters, options, defaults and price | none |

In the four generation tools the model list comes live from the Wiro AI catalog, most used first, so new models show up without a plugin update.

## Setup

1. Sign up at [wiro.ai](https://wiro.ai) and create a project at [wiro.ai/panel/project/new](https://wiro.ai/panel/project/new). Copy the project's API key. If the project uses signature authentication, copy the API secret as well.
2. In Dify, open **Plugins**, search the Marketplace for **Wiro AI Media** and install it.
3. Open the plugin, click **Authorize** (or **Set up**), paste the API key, and the API secret for a signature project, then save. Dify checks the key by reading one task row from your project, which costs nothing.

## Usage

### In a workflow

Add **Generate Image** to a workflow, pick a model and write the prompt, or pass it from an earlier node. The node outputs:

- `files`: the generated images, ready for an End node, an Answer node or a vision LLM;
- `text`: a short summary with the model, the run time, the cost and the file links;
- `json`: the task ID, task token, status, cost and file list.

To edit images, connect files to **Input images**. To pass settings a model has beyond the common inputs, put them in **Extra parameters** as JSON, for example `{"resolution": "2K"}`. **Get Model Parameters** shows the names and options each model takes.

### In an agent

Add the tools to an agent app. A request such as "make a 16:9 poster of a paper boat at sunrise" calls Generate Image, and "turn this summary into speech" calls Text to Speech. For other jobs the agent can call Search Models, then Get Model Parameters, then Run Any Model.

### Long jobs

Each tool waits for the result: up to 4 minutes for images and audio, and 8 minutes for video. A task that takes longer keeps running on Wiro AI. The tool then returns the task token, and **Get Task Result** collects the files when the task is done.

### Examples

Run Any Model with an image model:

```json
{"prompt": "A paper boat on a calm lake, watercolor", "ratio": "16:9", "quality": "medium"}
```

with the model ID `openai/gpt-image-2`. Required parameters you leave out get the model's catalog default where it has one.

Run Any Model with a chat model returns its text answer, for example the model ID `openai/gpt-5-nano` with `{"prompt": "Summarize this in one line: ..."}`.

## Credentials

| Field | Required | Notes |
| --- | --- | --- |
| API Key | yes | The API key of your Wiro AI project. |
| API Secret | no | Only for projects that use signature authentication. The plugin signs each request with it and never sends it. |

## Connection requirements

The plugin calls the Wiro AI API at `https://api.wiro.ai/v1` and downloads result files from Wiro AI's CDN (hosts under `wiro.ai`, such as `cdn1.wiro.ai`). A self-hosted Dify needs outbound HTTPS access to both. Input files from Dify are uploaded to your Wiro AI project first, so the model can read them from a public URL.

Files up to 50 MB come back as Dify files, which matches Dify's default plugin file limit. A larger result comes back as a link.

## Pricing

Each run is billed to your Wiro AI project at the model's price, and the cost of every run is in the tool's output. Search Models and Get Model Parameters show prices before you run anything. See [pricing](https://wiro.ai/docs/pricing) and each model's page on [wiro.ai/models](https://wiro.ai/models).

## Links

- Source code: [github.com/wiroai/Wiro-Dify-Plugin](https://github.com/wiroai/Wiro-Dify-Plugin)
- Wiro AI: [wiro.ai](https://wiro.ai)
- Run API docs: [wiro.ai/docs/run-a-model](https://wiro.ai/docs/run-a-model)
- Chat models in Dify: the [Wiro AI](https://github.com/wiroai/Wiro-Dify-Plugin/tree/main/models/wiro) model provider plugin
- Support: support@wiro.ai or [GitHub issues](https://github.com/wiroai/Wiro-Dify-Plugin/issues)
