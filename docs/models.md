# Choosing a model

The model is what decides *which tool to use* when you ask a question in words.
A bigger one gets that right more often — it's the single biggest lever on how
good LeSysBot feels. This page helps you pick one that fits your hardware.

Every model here supports tool calling, which LeSysBot needs. Using OpenAI or
another remote service instead? You can skip this page —
see [Settings](configuration.md#switching-model-backend).

**In a hurry:** `ollama pull qwen3.5:4b` works on almost anything and is what the
quick start uses. Move up a tier when you notice it picking the wrong tool.

---

## 1. Quick pick by GPU VRAM

VRAM numbers are approximate at Q4_K_M quantization; add ~1–2 GB overhead for
KV cache and OS.

| GPU VRAM | Recommended model | Pull command |
|---|---|---|
| 4 GB | Qwen3.5 4B (quick-start default) | `ollama pull qwen3.5:4b` |
| 8 GB | Qwen3.5 9B ⭐ | `ollama pull qwen3.5` |
| 12 GB | Gemma4 12B | `ollama pull gemma4:12b` |
| 16 GB | Qwen3 14B | `ollama pull qwen3:14b` |
| 24 GB | Qwen3.5 27B | `ollama pull qwen3.5:27b` |
| 48 GB+ | Llama 3.3 70B | `ollama pull llama3.3:70b` |

⭐ Best balance of quality and speed for most hardware.

**Alternatives worth knowing at each tier:**

| Tier | Model | VRAM | Why pick it |
|---|---|---|---|
| 4 GB | Llama 3.2 3B (`llama3.2`) | ~3.6 GB | Smaller still (~2 GB download); weaker tool calling |
| 8 GB | Gemma4 12B (`gemma4:12b`) | ~7.6 GB | Native function calling; multimodal |
| 12 GB | DeepSeek R1 14B (`deepseek-r1:14b`) | ~9.5 GB | Strong reasoning / chain-of-thought |
| 16 GB | Gemma4 e4b (`gemma4:e4b`) | ~9.6 GB | MoE — very fast for its quality |
| 24 GB | Qwen3 32B (`qwen3:32b`) | ~22 GB | Excellent instruction following |
| 48 GB+ | Qwen3.5 122B (`qwen3.5:122b`) | ~81 GB | Needs 2× 48 GB GPUs or large unified memory |

**Coding-heavy tools?** If your LeSysBot tools involve writing or reviewing code,
`qwen3-coder:30b` (~18 GB, MoE) is the strongest open coding model;
`deepseek-coder-v2` (~9 GB) is a good mid-size option.

**Apple Silicon** shares RAM and VRAM in one unified pool — use total RAM as
your budget with the tables above (16 GB RAM → the 8–12 GB tier). Pull the
`-mlx` tag variants for better performance: `ollama pull qwen3.5:9b-mlx`.

---

## 2. Tips

- **Tool calling quality**: Qwen3.5 and Gemma4 have the most reliable tool
  calling in 2026 — they rarely hallucinate function names or drop required
  parameters. If LeSysBot picks the wrong tool or none at all, try one of these
  before debugging anything else.
- **MoE models** (e.g. Qwen3-Coder 30B) load fewer active parameters per token —
  faster than their total size suggests.
- **Quantization**: Ollama picks a sensible quantization automatically. For
  explicit control, append `:q4_K_M` (smaller/faster) or `:q8_0` (higher
  quality, more VRAM).
- **Out of memory**: try the next smaller size or a MoE variant.
- **Large contexts**: Qwen3.5 models have a 256K context window — you can raise
  `agent.max_history` (default 50) safely on them.

---

## 3. Managing models with Ollama

The commands you'll actually need:

```bash
ollama list                 # what's downloaded
ollama pull qwen3.5         # download a model
ollama rm qwen3.5:4b        # delete one
ollama ps                   # what's loaded in GPU memory right now
ollama stop qwen3.5         # unload a model, free VRAM
ollama run qwen3.5          # chat REPL — quick test before wiring into LeSysBot
```

**Is the server running?**

```bash
curl http://localhost:11434/
# → Ollama is running
```

If not, start it: the official installer registers a systemd service
(`sudo systemctl start ollama`), or run `ollama serve` in a terminal. For server administration beyond this — bind
address, storage location, keep-alive tuning — see the
[official Ollama docs](https://github.com/ollama/ollama/tree/main/docs).

---

## 4. Pointing LeSysBot at the model

After pulling a model, set it in `config.yaml` (`~/.lesysbot/config.yaml` for an
installed setup):

```yaml
llm:
  base_url: "http://localhost:11434/v1"
  model: "qwen3.5"        # ← name from `ollama list`
  api_key: "ollama"
```

Or one-off on the command line:

```bash
lesysbot chat --model qwen3.5
```

Every backend (Ollama, vLLM, LlamaCpp, OpenAI) uses the same three settings —
the full matrix is in [Settings](configuration.md#switching-model-backend).
