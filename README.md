# Midas Agent

Budget-driven training engine that evolves coding agent workflows on SWE-bench. Selects configurations by **eta = Score / Cost**, trains through failure-driven reflection (GEPA), and adapts multi-step DAG workflows over time.

## Architecture

<p align="center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 340" width="720" height="340" font-family="system-ui, sans-serif" font-size="13">
  <!-- Boxes -->
  <rect x="260" y="10" width="200" height="44" rx="8" fill="#1a1a2e" stroke="#e94560" stroke-width="2"/>
  <text x="360" y="37" text-anchor="middle" fill="#fff" font-weight="bold">Training Loop</text>

  <rect x="520" y="90" width="180" height="44" rx="8" fill="#1a1a2e" stroke="#0f3460" stroke-width="2"/>
  <text x="610" y="117" text-anchor="middle" fill="#fff" font-weight="bold">DAG Executor</text>

  <rect x="520" y="180" width="180" height="44" rx="8" fill="#1a1a2e" stroke="#0f3460" stroke-width="2"/>
  <text x="610" y="207" text-anchor="middle" fill="#fff" font-weight="bold">SWE-bench Scorer</text>

  <rect x="260" y="270" width="200" height="44" rx="8" fill="#1a1a2e" stroke="#e94560" stroke-width="2"/>
  <text x="360" y="297" text-anchor="middle" fill="#fff" font-weight="bold">Failure Analyzer</text>

  <rect x="20" y="180" width="180" height="44" rx="8" fill="#1a1a2e" stroke="#e94560" stroke-width="2"/>
  <text x="110" y="207" text-anchor="middle" fill="#fff" font-weight="bold">GEPA Reflector</text>

  <rect x="20" y="90" width="180" height="44" rx="8" fill="#1a1a2e" stroke="#16c79a" stroke-width="2"/>
  <text x="110" y="117" text-anchor="middle" fill="#fff" font-weight="bold">Adaptive Workspace</text>

  <!-- Arrows -->
  <defs><marker id="ah" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6Z" fill="#888"/></marker></defs>

  <path d="M460,40 Q520,40 520,90" fill="none" stroke="#888" stroke-width="1.5" marker-end="url(#ah)"/>
  <path d="M610,134 L610,180" fill="none" stroke="#888" stroke-width="1.5" marker-end="url(#ah)"/>
  <path d="M520,202 Q360,240 360,270" fill="none" stroke="#888" stroke-width="1.5" marker-end="url(#ah)"/>
  <path d="M260,292 Q110,292 110,224" fill="none" stroke="#888" stroke-width="1.5" marker-end="url(#ah)"/>
  <path d="M110,180 L110,134" fill="none" stroke="#888" stroke-width="1.5" marker-end="url(#ah)"/>
  <path d="M200,100 Q260,70 260,40" fill="none" stroke="#888" stroke-width="1.5" marker-end="url(#ah)"/>

  <!-- Labels on arrows -->
  <text x="510" y="68" fill="#aaa" font-size="11">clone + run</text>
  <text x="620" y="163" fill="#aaa" font-size="11">score</text>
  <text x="420" y="255" fill="#aaa" font-size="11">fail traces</text>
  <text x="140" y="260" fill="#aaa" font-size="11">lessons</text>
  <text x="65" y="163" fill="#aaa" font-size="11">new config</text>
  <text x="180" y="58" fill="#aaa" font-size="11">champion</text>
</svg>
</p>

```
Scheduler ──► Workspace(s) ──► ReactAgent ──► Docker (SWE-bench)
                 │
         DAG: localize → investigate → fix → validate
```

### Three Layers

| Layer | Role |
|-------|------|
| **Scheduler** | Episode loop, budget allocation, checkpoint/resume |
| **Workspace** | Config evolution, DAG merge, GEPA reflection, adaptive selection |
| **ReactAgent** | Tool-calling agent (bash, str_replace_editor). Text response = done signal |

## Quick Start

```bash
# Install
poetry install

# Configure LLM
cat > .midas/config.yaml << EOF
model: openrouter/qwen/qwen3-coder-30b-a3b-instruct
api_key: sk-or-...
EOF

# Train on SWE-bench Verified
midas train --config train_config_evolution.yaml --train-dir my-run

# Train first N issues only
midas train --config train_config_evolution.yaml --issues 30

# Resume from checkpoint
midas train --resume .midas/train/my-run/

# Inference (interactive TUI)
midas infer --dag config.yaml

# Inference (eval on SWE-bench, frozen config)
midas infer --dag config.yaml --issues 50
```

## How Training Works

1. **Episode 1** -- Single-step ReactAgent solves an issue. On first success, `ConfigCreator` generates a multi-step DAG from the trace.

2. **Episodes 2+** -- `ConfigMerger` embeds each new issue into the DAG step prompts. `StepJudge` validates step completion (trust-based). Agent terminates by producing text (no `task_done` tool).

3. **Every N failures** -- GEPA triggers:
   - `FailureAnalyzer` extracts abstract lessons from failed traces (sees full trace + patch + gold test names)
   - `ConfigReflector` proposes a new whole-config from success + failure traces
   - Lessons condensed into prompts (no prompt inflation)

4. **Adaptive Workspaces** -- New config enters head-to-head against the champion. Winner selected by total issues solved. Both traces feed the next reflection cycle.

## Key Features

- **eta = S/C selection** -- efficiency-driven workspace competition
- **DAG workflows** -- multi-step plans (localize, investigate, fix, validate) that evolve
- **Failure-driven evolution (GEPA)** -- real execution outcomes, not proxy metrics
- **Adaptive workspaces** -- champion vs challenger head-to-head on identical issues
- **No task_done tool** -- text response = termination; unknown tool calls treated as done
- **ConfigMerger** -- embeds issue into step prompts (prevents overscoping), repairs structure via grafting
- **Checkpoint & resume** -- crash-safe, per-episode checkpoints
- **SWE-bench compatible** -- outputs `all_preds.jsonl` + traces for leaderboard submission

## Training Output

```
.midas/train/<run>/
├── checkpoint.json         # Resume metadata
├── train_config.yaml       # Saved config
├── all_preds.jsonl         # SWE-bench submission format
├── data/                   # Execution traces (GEPA dataset)
├── trajs/                  # Per-issue reasoning traces
└── log/
    ├── configs/            # DAG YAML per episode
    ├── action_logs/        # JSONL action logs
    ├── patches/            # Git patches
    └── best_config.yaml    # Best config at training end
```

## Requirements

- Python 3.11+
- Docker (SWE-bench execution)
- Poetry
- Any [LiteLLM](https://docs.litellm.ai/)-compatible model

## License

MIT
