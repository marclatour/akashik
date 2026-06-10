# Scripts

## bootstrap.sh

First-time setup for Akashik. Run from the repo root:

    bash scripts/bootstrap.sh

Sets up:
- `~/.akashik/` directory structure
- Python venv + dependencies
- LongMemEval benchmark data (auto-download)
- Ollama + `qwen2.5:1.5b` judge model (auto-install if Ollama present)
- CUAD source data (manual download required — license agreement)
- Optionally runs the test suite to verify installation (Y/n prompt)

If Ollama is missing, the script prints install instructions:

- macOS: `brew install ollama`
- Linux: `curl -fsSL https://ollama.com/install.sh | sh`
- start service: `ollama serve`
- then pull the judge model: `ollama pull qwen2.5:1.5b`
