#!/usr/bin/env bash
set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}✓${RESET} $1"; }
warn() { echo -e "${YELLOW}!${RESET} $1"; }
fail() { echo -e "${RED}✗${RESET} $1"; }
info() { echo -e "${BOLD}→${RESET} $1"; }
ensure_dir() {
    if [ -d "$1" ]; then
        ok "$1 already exists"
    else
        mkdir -p "$1"
        ok "$1 created"
    fi
}

echo ""
echo -e "${BOLD}Akashik Setup${RESET}"
echo "============================================"
echo ""

# ── 0. Check Python 3.13 ─────────────────────────────────────────────
info "Checking Python version..."
if ! command -v python3 &>/dev/null; then
    fail "Python 3 not found. Install from https://python.org"
    exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJOR=${PYVER%%.*}
PYMINOR=${PYVER#*.}
if (( PYMAJOR < 3 )) || { (( PYMAJOR == 3 )) && (( PYMINOR < 13 )); }; then
    warn "Python $PYVER found — Akashik targets 3.13+. Continuing anyway."
else
    ok "Python $PYVER"
fi

info "Checking required tools..."
for tool in curl git; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool available"
    else
        fail "$tool not found — required"
        exit 1
    fi
done

# ── 1. Create ~/.akashik/ directory structure ─────────────────────────
info "Creating ~/.akashik/ directory structure..."
ensure_dir ~/.akashik/stores/benchmarks/cuad
ensure_dir ~/.akashik/stores/benchmarks/cuad_b
ensure_dir ~/.akashik/stores/benchmarks/longmemeval_s_cleaned
ensure_dir ~/.akashik/stores/benchmarks/longmemeval_oracle
ensure_dir ~/.akashik/stores/corpora
ensure_dir ~/.akashik/data/benchmarks/cuad
ensure_dir ~/.akashik/data/benchmarks/longmemeval
ensure_dir ~/.akashik/data/benchmarks/acmb/personas
ensure_dir ~/.akashik/data/benchmarks/acmb/queries
ensure_dir ~/.akashik/stores/benchmarks/acmb
ensure_dir ~/.akashik/results/benchmarks
ensure_dir ~/.akashik/config
ensure_dir ~/.akashik/logs

# ── 2. Create defaults.toml if missing ───────────────────────────────
DEFAULTS=~/.akashik/config/defaults.toml
if [ ! -f "$DEFAULTS" ]; then
    cat > "$DEFAULTS" << 'EOF'
[retrieval]
document_gate_n = 5
abstention_threshold = 0.3

[judge]
model = "qwen2.5:1.5b"
votes = 3

[benchmark]
longmemeval_data = "~/.akashik/data/benchmarks/longmemeval"
cuad_data = "~/.akashik/data/benchmarks/cuad"
EOF
    ok "~/.akashik/config/defaults.toml created"
else
    ok "~/.akashik/config/defaults.toml already exists"
fi

# ── 3. Set up Python venv ─────────────────────────────────────────────
info "Setting up Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    ok ".venv created"
else
    ok ".venv already exists"
fi

DEPS_MARKER=.venv/.akashik_deps_installed
if [ ! -f "$DEPS_MARKER" ] || \
   [ pyproject.toml -nt "$DEPS_MARKER" ] || \
   ! .venv/bin/python -c "import pytest" &>/dev/null || \
   ! .venv/bin/python -c "from akashik import ingest_turn_fact, ingest_text, retrieve" &>/dev/null; then
    info "Installing dependencies..."
    .venv/bin/pip install --quiet --upgrade pip setuptools
    .venv/bin/pip install --quiet --no-build-isolation -e ".[dev]"
    .venv/bin/pip install --quiet -e ".[benchmark]"
    touch "$DEPS_MARKER"
    ok "Dependencies installed"
else
    ok "Dependencies already installed"
fi

if [ -z "$(ls -A ~/.akashik/data/benchmarks/acmb/personas 2>/dev/null)" ]; then
    info "Generating ACMB personas..."
    ./.venv/bin/python benchmark/acmb/generate_personas.py
    ok "ACMB personas generated"
else
    ok "ACMB personas already present"
fi

if [ -z "$(ls -A ~/.akashik/data/benchmarks/acmb/queries 2>/dev/null)" ]; then
    info "Generating ACMB queries..."
    ./.venv/bin/python benchmark/acmb/generate_queries.py 2>/dev/null || warn "generate_queries.py not found or failed — skipping"
else
    ok "ACMB queries already present"
fi

# ── 4. Download LongMemEval data if missing ───────────────────────────
info "Checking LongMemEval data..."
LME_DIR=~/.akashik/data/benchmarks/longmemeval
ORACLE=$LME_DIR/longmemeval_oracle.json
S_FILE=$LME_DIR/longmemeval_s_cleaned.json

if [ ! -f "$ORACLE" ]; then
    info "Downloading longmemeval_oracle.json (~15MB)..."
    curl -L --progress-bar \
        "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json" \
        -o "$ORACLE"
    ok "longmemeval_oracle.json downloaded"
else
    ok "longmemeval_oracle.json already present"
fi

if [ ! -f "$S_FILE" ]; then
    info "Downloading longmemeval_s_cleaned.json (~277MB)..."
    curl -L --progress-bar \
        "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json" \
        -o "$S_FILE"
    ok "longmemeval_s_cleaned.json downloaded"
else
    ok "longmemeval_s_cleaned.json already present"
fi

# ── 5. Check CUAD source data (license required, manual download) ─────
info "Checking CUAD source data..."
CUAD_DIR=~/.akashik/data/benchmarks/cuad
if [ -f "$CUAD_DIR/CUAD_v1.json" ] && [ -f "$CUAD_DIR/master_clauses.csv" ]; then
    ok "CUAD source data present"
else
    warn "CUAD source data not found at ~/.akashik/data/benchmarks/cuad/"
    warn "CUAD requires manual download (license agreement):"
    warn "  1. Visit https://www.atticusprojectai.org/cuad"
    warn "  2. Download CUAD_v1.json and master_clauses.csv"
    warn "  3. Place at ~/.akashik/data/benchmarks/cuad/"
    warn "  4. Run: .venv/bin/python benchmark/cuad/prepare.py"
fi

# ── 6. Check Ollama + qwen2.5:1.5b ───────────────────────────────────
info "Checking Ollama..."
if ! command -v ollama &>/dev/null; then
    warn "Ollama not found — required for QA judge and chat demo."
    echo -e "Install Ollama now? [Y/n] \c"
    read -r INSTALL_OLLAMA
    INSTALL_OLLAMA=${INSTALL_OLLAMA:-Y}
    if [[ "$INSTALL_OLLAMA" =~ ^[Yy]$ ]]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            info "Installing Ollama on macOS..."
            if command -v brew &>/dev/null; then
                brew install ollama
            else
                info "Homebrew not found — using official installer..."
                curl -fsSL https://ollama.com/install.sh | sh
            fi
        else
            info "Installing Ollama on Linux..."
            curl -fsSL https://ollama.com/install.sh | sh
        fi
        if command -v ollama &>/dev/null; then
            ok "Ollama installed"
        else
            warn "Ollama install may have failed — check output above"
            warn "Manual install: https://ollama.com/download"
        fi
    else
        warn "Skipping Ollama install — benchmark judge and chat demo will not work without it"
        warn "Install later: https://ollama.com/download"
    fi
else
    ok "Ollama installed"
fi

if command -v ollama &>/dev/null; then
    if ollama list 2>/dev/null | grep -q "qwen2.5:1.5b"; then
        ok "qwen2.5:1.5b model available"
    else
        info "Pulling qwen2.5:1.5b (~986MB)..."
        ollama pull qwen2.5:1.5b
        ok "qwen2.5:1.5b ready"
    fi
    info "Smoke-testing Ollama endpoint..."
    OLLAMA_TEST=$(curl -s -X POST http://localhost:11434/api/generate \
        -H "Content-Type: application/json" \
        -d '{"model":"qwen2.5:1.5b","prompt":"Say OK","stream":false,"options":{"temperature":0,"seed":0}}' \
        --max-time 15 2>/dev/null)
    if echo "$OLLAMA_TEST" | grep -q '"response"'; then
        ok "Ollama responding"
    else
        warn "Ollama not responding — start with: ollama serve"
    fi
fi

# ── 7. Run tests ──────────────────────────────────────────────────────
info "Running test suite..."
set +e
TEST_OUTPUT=$(.venv/bin/python -m pytest --tb=short -q 2>&1)
TEST_STATUS=$?
set -e
printf "%s\n" "$TEST_OUTPUT"
if [ "$TEST_STATUS" -eq 0 ]; then
    TEST_RESULT=$(printf "%s\n" "$TEST_OUTPUT" | grep "passed" | tail -1)
    if [ -z "$TEST_RESULT" ]; then
        TEST_RESULT="pytest completed successfully"
    fi
    ok "Tests: $TEST_RESULT"
else
    fail "Some tests failed — check output above"
    exit 1
fi

# ── 8. Summary ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Setup complete. Benchmark commands:${RESET}"
echo ""
echo "  # CUAD Mode A (clause-label queries)"
echo "  .venv/bin/python benchmark/run_cuad.py"
echo ""
echo "  # CUAD Mode B (natural language paraphrasing)"
echo "  .venv/bin/python benchmark/run_cuad_b.py"
echo ""
echo "  # LongMemEval Oracle"
echo "  .venv/bin/python benchmark/longmemeval/run_longmemeval.py \\"
echo "      --data ~/.akashik/data/benchmarks/longmemeval/longmemeval_oracle.json"
echo ""
echo "  # LongMemEval S (full noisy haystack)"
echo "  .venv/bin/python benchmark/longmemeval/run_longmemeval.py \\"
echo "      --data ~/.akashik/data/benchmarks/longmemeval/longmemeval_s_cleaned.json"
echo ""
echo "  # LongMemEval end-to-end QA generation"
echo "  .venv/bin/python benchmark/longmemeval/run_longmemeval.py \\"
echo "      --data ~/.akashik/data/benchmarks/longmemeval/longmemeval_s_cleaned.json \\"
echo "      --generate-answers"
echo ""
echo "  # QA judge (after benchmark run with --keep-output)"
echo "  .venv/bin/python benchmark/longmemeval/run_judge.py \\"
echo "      --results /tmp/akashik_lme_*.jsonl \\"
echo "      --data ~/.akashik/data/benchmarks/longmemeval/longmemeval_oracle.json"
echo ""
echo "  # ACMB benchmark"
echo "  .venv/bin/python benchmark/acmb/run_acmb.py"
echo ""
echo "  # Chat demo"
echo "  .venv/bin/python examples/chat_with_memory.py --reset"
echo ""
