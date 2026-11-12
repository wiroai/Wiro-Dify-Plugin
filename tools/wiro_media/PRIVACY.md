# Privacy Policy

This policy covers the Wiro AI Media tool plugin for Dify, published by Wiro AI Inc.

## What the plugin sends

When a workflow or agent runs one of the tools, the plugin sends the job to the Wiro AI API at `https://api.wiro.ai/v1`. A job carries:

- the prompt, text or message you give the tool, and the settings you chose;
- input files you connect to the tool, such as images, audio or video. For models and workflows the plugin uploads them to your Wiro AI project's storage first, so they can be read from a public URL. Ask Studio and Message Agent send them with the message;
- your Wiro AI API key. If you entered an API secret, the plugin uses it to sign the request and does not send it.

Where the job goes depends on the tool:

- the model tools and Run Any Model start a task on the model you picked;
- Run Workflow runs your saved workflow with the inputs you give it;
- Ask Studio sends your message, files and session name to Wiro AI Studio, with the chat model you picked;
- Message Agent sends your message, files and session name to the deployed agent you picked. The agent handles it with its own settings, skills and connected accounts.

The plugin then reads the status of the task, workflow run or reply from the same API and downloads the result files from Wiro AI's CDN, so Dify can store them as files. Search Models and Get Model Parameters only read the public model catalog. To fill its drop-down lists, the plugin reads the names of your workflows and agents and the chat models Studio offers.

## What the plugin stores and logs

The plugin does not collect, store or log your prompts, messages, files or credentials. It keeps no data between runs apart from a short-lived copy of public model details in memory. Dify stores the credentials you enter in its own encrypted storage, and stores the result files the tools return.

## Data kept on Wiro AI

Input files you connect and the files a model produces stay in your Wiro AI project, linked to the task, and can be deleted there. Workflow runs, Studio sessions and agent conversations stay in your Wiro AI workspace, as they do when you start them on wiro.ai. Wiro AI runs each job with the model you picked, either on its own GPUs or through the company that provides the model, and bills it to your project; a message to an agent uses the agent's credits. How Wiro AI handles this data is described in the [Wiro AI Privacy Policy](https://wiro.ai/agreement/privacy-policy).

## Contact

Questions about this policy: support@wiro.ai.
