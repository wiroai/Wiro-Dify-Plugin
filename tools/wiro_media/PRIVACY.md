# Privacy Policy

This policy covers the Wiro AI Media tool plugin for Dify, published by Wiro AI Inc.

## What the plugin sends

When a workflow or agent runs one of the tools, the plugin sends the job to the Wiro AI API at `https://api.wiro.ai/v1`. A job carries:

- the prompt or text you give the tool, and the model settings you chose;
- input files you connect to the tool, such as images. The plugin uploads them to your Wiro AI project's storage first, so the model can read them from a public URL;
- your Wiro AI API key. If you entered an API secret, the plugin uses it to sign the request and does not send it.

The plugin then reads the task status from the same API and downloads the result files from Wiro AI's CDN, so Dify can store them as files. Search Models and Get Model Parameters only read the public model catalog.

## What the plugin stores and logs

The plugin does not collect, store or log your prompts, files or credentials. It keeps no data between runs apart from a short-lived copy of public model details in memory. Dify stores the credentials you enter in its own encrypted storage, and stores the result files the tools return.

## Data kept on Wiro AI

Input files you connect and the files a model produces stay in your Wiro AI project, linked to the task, and can be deleted there. Wiro AI runs each job with the model you picked, either on its own GPUs or through the company that provides the model, and bills it to your project. How Wiro AI handles this data is described in the [Wiro AI Privacy Policy](https://wiro.ai/agreement/privacy-policy).

## Contact

Questions about this policy: support@wiro.ai.
