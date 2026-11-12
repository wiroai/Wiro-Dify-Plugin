# Wiro AI

Use the chat models on the Wiro AI LLM gateway in Dify: GPT from OpenAI, Claude from Anthropic, Gemini from Google, Grok from xAI, DeepSeek, Qwen, ByteDance Seed, Kimi, GLM and more. The same Wiro AI API key also brings text to speech and speech to text models from ElevenLabs, Google, OpenAI Whisper and others for Dify's voice features.

The plugin ships the gateway's model list with each model's details filled in: context size, output token limit, price per million tokens, and whether the model reads images and PDF files, calls tools and returns JSON that follows a schema. The voice models come with their voices from the Wiro AI catalog. A model added to Wiro AI later can be added by its ID, and the plugin reads its details from the catalog.

## Setup

1. Sign up at [wiro.ai](https://wiro.ai) and create a project at [wiro.ai/panel/project/new](https://wiro.ai/panel/project/new). Copy the project's API key. If the project uses signature authentication, copy the API secret as well.
2. In Dify, open **Plugins**, search the Marketplace for **Wiro AI** and install it.
3. Open **Settings > Model Provider**, find **Wiro AI** and click **Setup**.
4. Paste the API key, and the API secret for a signature project, then save. Dify checks the key with a request to the gateway's model list, which costs nothing.

## Chat models

Pick a Wiro AI model wherever Dify asks for an LLM: a chatbot, an agent, or an LLM node in a workflow or chatflow. Model IDs use the `owner/model` form, the same IDs as on the [Wiro AI model page](https://wiro.ai/models?categories=llm-tool-call). A few examples:

| Model ID | Notes |
| --- | --- |
| `openai/gpt-5-4-mini` | images and PDF input, tools, JSON Schema |
| `claude/sonnet-5` | 1M-token context, images and PDF input, tools |
| `google/gemini-3-5-flash` | 1M-token context, images and PDF input |
| `deepseek/v4-1-flash` | low price per token, tools, JSON Schema |
| `xai/grok-4-5` | images and PDF input, tools |

Examples of what works:

- **Agents and tool calling.** Models with tool calling work in agent apps and in the Agent node.
- **Structured output.** Turn on structured output in an LLM node. Models that take JSON Schema get the schema natively; the others can use the JSON object response format.
- **Images and documents.** Attach images or PDF files to a model that reads them. The plugin sends PDFs as file parts.
- **Reasoning effort and verbosity.** Models that support them show these controls in the model settings.

## Text to speech and speech to text

In **Settings > Model Provider**, open **Default Models** and choose Wiro AI models as the **Text-to-Speech Model** and the **Speech-to-Text Model**. Then turn on **Text to Speech** and **Speech to Text** in a chat app's **Features** and pick a voice. The app reads its answers aloud and turns voice input into text.

| Model ID | Type |
| --- | --- |
| `elevenlabs/eleven-v4` | text to speech |
| `elevenlabs/eleven-v4-turbo` | text to speech, at half the price of `elevenlabs/eleven-v4` |
| `google/gemini-3-1-tts` | text to speech |
| `wiro/kokoro-tts` | text to speech |
| `elevenlabs/speech-to-text` | speech to text |
| `openai/whisper-large-v3` | speech to text |

Dify's voice picker lists each model's voices, for example 21 on `elevenlabs/eleven-v4` and 54 on `wiro/kokoro-tts`. The audio comes back as MP3. Each model's settings and price are on its page on [wiro.ai/models](https://wiro.ai/models).

### Add a model by ID

Open **Settings > Model Provider > Wiro AI > Add Model**, choose the model type, and type the model ID (for example `openai/gpt-5-4-mini`, or `elevenlabs/eleven-v4-turbo` for text to speech) and the API key. The plugin looks the model up in the Wiro AI catalog and fills in its details: the context size, output limit and features of a chat model, or the voices of a text to speech model. An ID that is not a model of that type is refused with a short reason.

## Credentials

| Field | Required | Notes |
| --- | --- | --- |
| API Key | yes | The API key of your Wiro AI project. |
| API Secret | no | Only for projects that use signature authentication. Chat requests send `key:secret` as the Bearer token, as the gateway expects. Voice model requests are signed with it. |

Dify stores the credentials. The plugin only sends them to Wiro AI.

## Connection requirements

Chat models use `https://llm.wiro.ai/v1`, the OpenAI-compatible Chat Completions endpoint and the model list. Voice models use the Wiro AI API at `https://api.wiro.ai/v1`, and their audio and transcripts come from Wiro AI's CDN at `cdn1.wiro.ai`. A self-hosted Dify needs outbound HTTPS access to these three hosts.

## Pricing

Requests are billed to your Wiro AI project at the model's price. Dify shows each chat model's price per million input and output tokens, and the gateway reports the billed amount with each answer. Models that run on Wiro AI's own GPUs are billed by processing time. Voice models are billed per run at the price on each model's page. See [pricing](https://wiro.ai/docs/pricing).

## Links

- Source code: [github.com/wiroai/Wiro-Dify-Plugin](https://github.com/wiroai/Wiro-Dify-Plugin)
- Wiro AI: [wiro.ai](https://wiro.ai)
- LLM gateway docs: [wiro.ai/docs/completions-api](https://wiro.ai/docs/completions-api)
- Run API docs: [wiro.ai/docs/run-a-model](https://wiro.ai/docs/run-a-model)
- Image, video and audio models in Dify: the [Wiro AI Media](https://github.com/wiroai/Wiro-Dify-Plugin/tree/main/tools/wiro_media) tool plugin
- Support: support@wiro.ai or [GitHub issues](https://github.com/wiroai/Wiro-Dify-Plugin/issues)
