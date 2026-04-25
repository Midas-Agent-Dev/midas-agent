# Midas Agent

A self-improving coding agent that learns from its own failures. Given a set of GitHub issues, Midas trains a multi-step DAG workflow through a closed-loop process: solve issues, analyze failures, reflect on what went wrong, and evolve the workflow prompts — so the next batch of issues benefits from past mistakes.

## Motivation

Most coding agents use a fixed prompt and hope for the best. When they fail, the failure is discarded. Midas closes that loop:

1. The agent solves issues using a **multi-step DAG** (localize → investigate → fix → validate)
2. Failed attempts are **analyzed** — an LLM identifies which step went wrong and extracts an abstract lesson
3. A **reflector** rewrites the DAG prompts to incorporate those lessons
4. The new config is **validated head-to-head** against the old one on fresh issues
5. The winner survives. Repeat.

Over episodes, the DAG prompts evolve from generic instructions into battle-tested guidance like *"don't edit test files"*, *"fix the error message, not the condition logic"*, *"actually change the behavior, don't just add a deprecation warning."*

## Pipeline

### 1. Training Loop (per issue)

```
Issue → ConfigMerger → DAG Executor → Patch → SWE-bench Scorer → Record Trace
                           │
                    step 1 → step 2 → ... → step N
                    (StepJudge validates each transition)
```

For each SWE-bench issue, `ConfigMerger` embeds the issue into the DAG step prompts. The agent executes each step in sequence — when it stops calling tools and produces text, `StepJudge` validates the claim and advances to the next step. The resulting patch is scored by SWE-bench. Both successes and failures are recorded with their full traces.

### 2. Config Evolution — the Closed Loop (every N episodes)

The key insight: SWE-bench provides a **gold standard** — the exact tests that must pass. When the agent fails, we know *why* it failed because we can compare the agent's patch against the gold tests. This ground truth is what closes the loop:

```mermaid
flowchart TD
    A["Accumulated Traces<br/><i>success + failure traces</i>"] --> B
    B["Failure Analyzer<br/><i>compares agent's patch against</i><br/><i>gold test expectations</i><br/><i>→ which step? what mistake?</i>"] --> C
    C["Config Reflector<br/><i>sees: success traces + failure lessons</i><br/><i>rewrites DAG prompts to avoid</i><br/><i>past mistakes</i>"] --> D
    D["Candidate Config"] --> E
    E["Head-to-Head Validation<br/><i>champion vs candidate</i><br/><i>same future issues, compare scores</i>"] --> F
    F{candidate solves<br/>more issues?}
    F -->|"yes"| G["Candidate → new champion"]
    F -->|"no"| H["Keep champion"]
    G --> I["Next N episodes"]
    H --> I
    I -->|"new traces"| A

    style A fill:#0d1117,stroke:#58a6ff,color:#fff
    style B fill:#0d1117,stroke:#f85149,color:#fff
    style C fill:#0d1117,stroke:#f85149,color:#fff
    style D fill:#0d1117,stroke:#f0883e,color:#fff
    style E fill:#0d1117,stroke:#3fb950,color:#fff
    style F fill:#0d1117,stroke:#f0883e,color:#fff
    style G fill:#0d1117,stroke:#3fb950,color:#fff
    style H fill:#0d1117,stroke:#58a6ff,color:#fff
    style I fill:#0d1117,stroke:#58a6ff,color:#fff
```

Without the gold standard, failure analysis would be guessing. With it, the analyzer can say precisely: *"the agent changed the condition logic but the gold test asserts on the error message string — the fix should have changed the message, not the condition."* This concrete signal is what makes the loop converge.

## Quick Start

```bash
poetry install

# Configure LLM (any LiteLLM-compatible provider)
cat > .midas/config.yaml << EOF
model: minimax/MiniMax-M2.5
api_key: sk-...
api_base: https://api.minimax.io/v1
EOF

# Train (evolves DAG config over episodes)
midas train --config train_config_evolution.yaml --issues 30

# Resume from checkpoint
midas train --resume .midas/train/my-run/

# Eval with frozen config (no evolution)
midas infer --dag .midas/train/my-run/log/configs/ws-0_ep10.yaml --issues 50

# Interactive mode
midas infer --dag config.yaml
```

## Key Features

- **Closed-loop learning** — failures are analyzed, lessons extracted, prompts improved
- **DAG workflows** — multi-step plans that evolve from generic to battle-tested
- **Adaptive workspaces** — champion vs challenger, winner survives
- **No task_done tool** — text response = done; unknown tool calls treated as termination
- **ConfigMerger** — embeds issue into step prompts to prevent overscoping
- **Rich failure analysis** — sees full trace, patch diff, and gold test names
- **Checkpoint & resume** — per-episode snapshots, crash-safe

## Training Output

```
.midas/train/<run>/
├── checkpoint.json
├── train_config.yaml
├── all_preds.jsonl          # SWE-bench submission
├── data/                    # Success + failure traces (GEPA dataset)
└── log/configs/             # DAG YAML per episode (shows prompt evolution)
```
