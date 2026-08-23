---
name: switch-llm-backend
description: Point LeSysBot at a different LLM backend or model — Ollama, vLLM, LlamaCpp, OpenAI, or any OpenAI-compatible endpoint — including model recommendations by GPU VRAM and Ollama model management. Use when asked to "change from ollama to vllm", "use OpenAI", "switch the model", "use a bigger/smaller model", or "the model is bad at tool calling".
---

# Switch LLM backend or model

All backends speak the same OpenAI-compatible API — switching is **only three
config values** (`base_url`, `model`, `api_key`); no code changes ever.

## The backend matrix

| Backend | `base_url` | `api_key` |
|---|---|---|
| **Ollama** (default) | `http://localhost:11434/v1` | `ollama` (any non-empty string) |
| **vLLM** | `http://localhost:8000/v1` | `vllm` (any non-empty string) |
| **LlamaCpp server** | `http://localhost:8080/v1` | `llama` |
| **OpenAI** | `https://api.openai.com/v1` | real `sk-…` key |
| **Anything else** (LM Studio, a proxy…) | its endpoint incl. `/v1` | whatever it needs |

## Switch permanently

Edit the `llm:` block in the active config (`~/.lesysbot/config.yaml` for an
installed setup) and restart:

```yaml
# Example: Ollama → vLLM
llm:
  base_url: "http://localhost:8000/v1"
  model: "meta-llama/Llama-3.2-8B-Instruct"   # the model id the vLLM server serves
  api_key: "vllm"
```

```yaml
# Example: → OpenAI
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "sk-..."        # stored in config.yaml — keep the file private
```

Apply: `systemctl --user restart lesysbot` (Linux) /
`launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot` (macOS) /
`Stop-ScheduledTask -TaskName LeSysBot; Start-ScheduledTask -TaskName LeSysBot`
(Windows). CLI sessions pick it up on next launch.

## Switch for one session (no config edit)

```bash
lesysbot chat --model qwen3.5
lesysbot chat --base-url http://localhost:8000/v1 --model meta-llama/Llama-3.2-8B-Instruct
LESYSBOT_LLM__BASE_URL=https://api.openai.com/v1 LESYSBOT_LLM__MODEL=gpt-4o \
  LESYSBOT_LLM__API_KEY=sk-... lesysbot chat
```

Precedence: CLI flags → `LESYSBOT_*` env vars → config file.

## Picking a local model (Ollama)

LeSysBot **requires tool calling** — the model must support it. By GPU VRAM
(Q4_K_M quantization; Apple Silicon: use total RAM as the budget and prefer
`-mlx` tag variants):

| VRAM | Model | Pull |
|---|---|---|
| 4 GB | Qwen3.5 4B (or Llama 3.2 3B for a tiny start) | `ollama pull qwen3.5:4b` |
| 8 GB | Qwen3.5 9B ⭐ best balance | `ollama pull qwen3.5` |
| 12 GB | Gemma4 12B | `ollama pull gemma4:12b` |
| 16 GB | Qwen3 14B | `ollama pull qwen3:14b` |
| 24 GB | Qwen3.5 27B | `ollama pull qwen3.5:27b` |
| 48 GB+ | Llama 3.3 70B | `ollama pull llama3.3:70b` |

- **Unreliable tool calling** (wrong tool, missing params)? Qwen3.5 and Gemma4
  are the most reliable tool callers — try one before debugging anything else.
- **Coding-heavy tools**: `qwen3-coder:30b` (~18 GB) or `deepseek-coder-v2` (~9 GB).
- **Out of memory**: next smaller size or an MoE variant.

Ollama management:

```bash
ollama list        # downloaded models        ollama ps      # loaded in VRAM now
ollama pull NAME   # download                 ollama stop NAME  # free VRAM
ollama rm NAME     # delete                   ollama run NAME   # quick REPL test
curl http://localhost:11434/    # "Ollama is running"? if not: sudo systemctl start ollama
```

## Verify the switch

- Ask the bot anything conversational — a reply proves the backend answers.
- `LLM unavailable` → the backend isn't reachable at `base_url`;
  `model "x" not found` → pull it (`ollama pull x`) or fix `llm.model`.
  Slash commands keep working with no model at all.

## Related

- All config mechanics: [configure-lesysbot](../configure-lesysbot/SKILL.md).
- Restart commands: [manage-service](../manage-service/SKILL.md).
