# Privacy Policy

This policy covers the Wiro AI model provider plugin for Dify, published by Wiro AI Inc.

## What the plugin sends

When you use a Wiro AI model in Dify, the plugin sends the request to the Wiro AI LLM gateway at `https://llm.wiro.ai/v1`. A request carries:

- the messages of the conversation, including any images or documents you attach;
- tool definitions and tool results, when the app uses tools;
- the model settings you chose, such as the output token limit;
- your Wiro AI API key, and the API secret if you entered one, to authenticate the request.

When you save credentials or add a model, the plugin also reads the gateway's model list, which carries no content.

## What the plugin stores and logs

The plugin does not collect, store or log your messages, files or credentials. It keeps no data between requests apart from a short-lived copy of the public model catalog in memory. Dify stores the credentials you enter in its own encrypted storage.

## Third parties

Wiro AI processes each request to run the model you picked, and bills it to your project. Depending on the model, Wiro AI passes the request to the company that provides it, such as OpenAI, Anthropic, Google, xAI or DeepSeek, or runs it on its own GPUs. How Wiro AI handles this data is described in the [Wiro AI Privacy Policy](https://wiro.ai/agreement/privacy-policy).

## Contact

Questions about this policy: support@wiro.ai.
