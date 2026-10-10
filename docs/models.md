# Choosing a model

The model decides which tool to use when you ask in words. A bigger model gets
it right more often. Pick the largest one that fits your GPU.

Using OpenAI or another remote service? Skip this page and see
[Settings](configuration.md#use-a-different-backend).

## Pick by GPU memory

| GPU memory | Model | Download it |
|---|---|---|
| 4 GB | Qwen3.5 4B *(the default)* | `ollama pull qwen3.5:4b` |
| 8 GB | Qwen3.5 9B ⭐ | `ollama pull qwen3.5` |
| 12 GB | Gemma4 12B | `ollama pull gemma4:12b` |
| 16 GB | Qwen3 14B | `ollama pull qwen3:14b` |
| 24 GB | Qwen3.5 27B | `ollama pull qwen3.5:27b` |
| 48 GB+ | Llama 3.3 70B | `ollama pull llama3.3:70b` |

⭐ The best balance of quality and speed for most machines.

## Switch to it

```bash
ollama pull qwen3.5
lesysbot chat --model qwen3.5     # try it for one session
```

Happy with it? Run `lesysbot setup` and pick it from the list, or set
`llm.model` in `~/.lesysbot/config.yaml` and restart the service.

## Tips

- **Wrong tool, or no tool at all?** Try a bigger model before anything else.
  Qwen3.5 and Gemma4 are the most reliable at calling tools.
- **Out of memory?** Go one size down.
- **First reply is slow?** The model is loading. Later replies are faster.

## Ollama basics

```bash
ollama list          # downloaded models
ollama ps            # models loaded right now
ollama rm NAME       # delete a model
curl localhost:11434 # prints "Ollama is running" if the server is up
```

Not running? `sudo systemctl start ollama`, or `ollama serve` in a terminal.
More in the [Ollama docs](https://github.com/ollama/ollama/tree/main/docs).
