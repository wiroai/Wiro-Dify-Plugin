# Wiro AI Media

Create and edit images, make videos and talking avatars, turn text into speech and speech into text, and make music and 3D models in Dify workflows, chatflows and agents with models on Wiro AI. The same plugin runs any of the 1,000+ models on Wiro AI by ID, your saved Wiro AI workflows, Wiro AI Studio and your deployed agents. One Wiro AI API key covers all of them, and the results come back to Dify as files.

## Tools

| Tool | What it does | Default model |
| --- | --- | --- |
| Generate Image | Creates an image from a prompt, or edits the input images | `google/nano-banana-2` |
| Edit Image | Changes an image with a text instruction | `google/nano-banana-2` |
| Upscale Image | Makes an image larger and sharper | `xinntao/real-esrgan` |
| Remove Background | Cuts out the subject on a transparent background | `wiro/remove-background` |
| Generate Video | Creates a video from a prompt, a start image or both | `bytedance/seedance-v1-pro-fast` |
| Image to Video | Animates a still image | `bytedance/seedance-v1-pro-fast` |
| Lipsync | Makes the face in a picture speak, from speech audio or a script | `pruna/p-video-avatar` |
| Text to Speech | Reads text aloud in the chosen voice | `elevenlabs/eleven-v4` |
| Speech to Text | Transcribes an audio or video file | `elevenlabs/speech-to-text` |
| Generate Music | Creates music or sound effects from a description | `elevenlabs/text-to-music-v2` |
| Generate 3D | Turns a picture of an object into a 3D model (GLB file) | `microsoft/trellis-2` |
| Run Any Model | Runs any Wiro AI model by ID with its own parameters | any model |
| Run Workflow | Runs one of your saved Wiro AI workflows with its inputs | your workflows |
| Ask Studio | Asks Wiro AI Studio, which picks the models, runs them and replies with the files | chosen by Studio |
| Message Agent | Sends a message to one of your deployed Wiro AI agents and returns its answer | your agents |
| Get Task Result | Collects the files of a task or workflow run that was still running | none |
| Search Models | Finds models by name and task | none |
| Get Model Parameters | Lists a model's parameters, options, defaults and price | none |

In the eleven tools built for one kind of job, the model list comes live from the Wiro AI catalog for that job, most used first, so new models show up without a plugin update. Run Workflow and Message Agent list your own workflows and agents, and Ask Studio lists the chat models Studio can think with.

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

The other model tools work the same way. Edit Image, Upscale Image, Remove Background, Image to Video and Generate 3D take a file from an earlier node or the start form. Lipsync takes a picture of a face and either speech audio or a script, on models that voice text themselves. Speech to Text returns the transcript as `text`, and Generate 3D returns a GLB file.

To pass settings a model has beyond the common inputs, put them in **Extra parameters** as JSON, for example `{"resolution": "2K"}`. **Get Model Parameters** shows the names and options each model takes.

### In an agent

Add the tools to an agent app. A request such as "make a 16:9 poster of a paper boat at sunrise" calls Generate Image, "remove the background of this photo" calls Remove Background, and "transcribe this recording" calls Speech to Text. For other jobs the agent can call Search Models, then Get Model Parameters, then Run Any Model.

### Your workflows, Studio and agents

- **Run Workflow** lists the workflows saved in your Wiro AI workspace. Pass the inputs as JSON with the input names the workflow uses, for example `{"prompt": "a red boat"}`. Inputs you leave out keep their saved value or default. Files go to the workflow's first file input, or to the one named in **File input**. The tool returns the results of the workflow's output step, files as Dify files and text as text, with the run's total cost.
- **Ask Studio** sends your request, and any files, to Wiro AI Studio. Studio picks the models, runs them and replies with text and files. Each **Session** keeps its own conversation, so a later request in the same session can build on earlier results.
- **Message Agent** sends a message, and any files, to one of your deployed Wiro AI agents and returns its answer with the files it links. Each session keeps its own conversation, and each message uses the agent's credits.

### Long jobs

Each tool waits for the result: up to 4 minutes for images, speech and music, 5 minutes for upscaling, transcription and agent answers, and 8 minutes for video, lipsync, 3D models, workflows and Studio. Run Any Model, Run Workflow, Ask Studio, Message Agent and Get Task Result have a **Wait seconds** setting. A task or workflow run that takes longer keeps running on Wiro AI: the tool returns its token, and **Get Task Result** collects the files when it is done. When Studio or an agent needs longer, its answer appears in the same session on Wiro AI.

### Examples

Run Any Model with an image model:

```json
{"prompt": "A paper boat on a calm lake, watercolor", "ratio": "16:9", "quality": "medium"}
```

with the model ID `openai/gpt-image-2`. Required parameters you leave out get the model's catalog default where it has one.

Run Any Model with a chat model returns its text answer, for example the model ID `openai/gpt-5-nano` with `{"prompt": "Summarize this in one line: ..."}`.

Edit Image with a product photo and the prompt "Put the bottle on a marble table in soft morning light" returns the edited photo. Add Upscale Image and Remove Background after it for a large cutout of the product.

Lipsync with a portrait and the script "Welcome to our store. Ask me anything about our products." returns a talking video of that face.

Run Workflow with a workflow whose inputs are `prompt` and `style` takes:

```json
{"prompt": "A paper boat on a pond", "style": "watercolor"}
```

## Credentials

| Field | Required | Notes |
| --- | --- | --- |
| API Key | yes | The API key of your Wiro AI project. |
| API Secret | no | Only for projects that use signature authentication. The plugin signs each request with it and never sends it. |

## Connection requirements

The plugin calls the Wiro AI API at `https://api.wiro.ai/v1` and downloads result files from Wiro AI's CDN (hosts under `wiro.ai`, such as `cdn1.wiro.ai`). A self-hosted Dify needs outbound HTTPS access to both. Input files from Dify are uploaded to your Wiro AI project first, so the model can read them from a public URL.

Files up to 50 MB come back as Dify files, which matches Dify's default plugin file limit. A larger result comes back as a link.

## Pricing

Each run is billed to your Wiro AI project at the model's price, and the cost of every run is in the tool's output. Run Workflow shows the run's total cost, and Ask Studio the cost of Studio's chat and of the models it ran. Search Models and Get Model Parameters show prices before you run anything. See [pricing](https://wiro.ai/docs/pricing) and each model's page on [wiro.ai/models](https://wiro.ai/models).

## Links

- Source code: [github.com/wiroai/Wiro-Dify-Plugin](https://github.com/wiroai/Wiro-Dify-Plugin)
- Wiro AI: [wiro.ai](https://wiro.ai)
- Run API docs: [wiro.ai/docs/run-a-model](https://wiro.ai/docs/run-a-model)
- Workflows, Studio and agent messaging: [wiro.ai/docs/workflows](https://wiro.ai/docs/workflows), [wiro.ai/docs/studio](https://wiro.ai/docs/studio), [wiro.ai/docs/agent-messaging](https://wiro.ai/docs/agent-messaging)
- Chat and voice models in Dify: the [Wiro AI](https://github.com/wiroai/Wiro-Dify-Plugin/tree/main/models/wiro) model provider plugin
- Support: support@wiro.ai or [GitHub issues](https://github.com/wiroai/Wiro-Dify-Plugin/issues)
