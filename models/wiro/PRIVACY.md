# Privacy Policy

This policy covers the Wiro AI model provider plugin for Dify, published by Wiro AI Inc.

## What the plugin sends

When you use a Wiro AI chat model in Dify, the plugin sends the request to the Wiro AI LLM gateway at `https://llm.wiro.ai/v1`. A request carries:

- the messages of the conversation, including any images or documents you attach;
- tool definitions and tool results, when the app uses tools;
- the model settings you chose, such as the output token limit;
- your Wiro AI API key, and the API secret if you entered one, to authenticate the request.

When you use a Wiro AI text to speech or speech to text model, the plugin sends the job to the Wiro AI API at `https://api.wiro.ai/v1`. A job carries the text to read aloud and the voice, or the recording to transcribe. The plugin uploads the recording to your Wiro AI project's storage first, so the model can read it from a public URL. These requests carry your API key; if you entered an API secret, the plugin signs them with it and does not send it. The plugin then reads the task status from the same API and downloads the audio or the transcript from Wiro AI's CDN.

When you save credentials or add a model, the plugin also reads the gateway's model list, the Wiro AI model catalog or one task row of your project to check the key. These requests carry no content.

## What the plugin stores and logs

The plugin does not collect, store or log your messages, recordings, files or credentials. It keeps no data between requests apart from a short-lived copy of public model details in memory. Dify stores the credentials you enter in its own encrypted storage.

## Data kept on Wiro AI

Recordings you transcribe and the audio a model produces stay in your Wiro AI project, linked to the task, and can be deleted there.

## Third parties

Wiro AI processes each request to run the model you picked, and bills it to your project. Depending on the model, Wiro AI passes the request to the company that provides it, such as OpenAI, Anthropic, Google, xAI, DeepSeek or ElevenLabs, or runs it on its own GPUs. How Wiro AI handles this data is described in the [Wiro AI Privacy Policy](https://wiro.ai/agreement/privacy-policy).

## Contact

Questions about this policy: support@wiro.ai.
