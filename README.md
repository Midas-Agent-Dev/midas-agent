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

```mermaid
flowchart TD
    A["<b>Training Loop</b><br/><i>for each SWE-bench issue</i>"] -->|"issue + merged config"| B
    B["<b>DAG Executor</b><br/><i>multi-step DAG, generated from first success</i><br/><i>StepJudge validates each transition</i>"] -->|"patch"| C
    C["<b>SWE-bench Scorer</b>"] -->|"score=0"| D
    C -.->|"score=1 → record trace"| A
    D["<b>Failure Analyzer</b><br/><i>sees: trace + patch + gold test names</i><br/><i>outputs: which step failed + abstract lesson</i>"] -->|"lessons"| E
    E["<b>Config Reflector</b><br/><i>success traces + failure lessons</i><br/><i>→ rewrites all step prompts</i>"] -->|"new config"| F
    F["<b>Adaptive Workspace</b><br/><i>champion vs challenger, head-to-head</i><br/><i>winner selected by issues solved</i>"] -->|"champion config"| A

    style A fill:#1a1a2e,stroke:#e94560,color:#fff
    style B fill:#1a1a2e,stroke:#0f3460,color:#fff
    style C fill:#1a1a2e,stroke:#0f3460,color:#fff
    style D fill:#1a1a2e,stroke:#e94560,color:#fff
    style E fill:#1a1a2e,stroke:#e94560,color:#fff
    style F fill:#1a1a2e,stroke:#16c79a,color:#fff
```

### How the loop works

| Step | What happens |
|------|-------------|
| **Train** | Pick an issue, merge it into the DAG step prompts, run in Docker |
| **Execute** | Agent follows generated DAG steps. Text response = step done. StepJudge validates. |
| **Score** | SWE-bench runs gold tests. Pass (1.0) or fail (0.0). |
| **Analyze** | On failure: LLM sees full trace + agent's patch + gold test names. Identifies which step failed and extracts an abstract lesson. |
| **Reflect** | Every N episodes: ConfigReflector sees all success + failure traces. Rewrites DAG prompts — lessons are condensed in, not appended. |
| **Compete** | New config enters head-to-head against champion on fresh issues. Winner keeps its spot. |

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
