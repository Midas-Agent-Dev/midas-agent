# Midas Agent — Integration Test Plan

> **Status:** Draft v1.
> **Scope:** Integration tests only. Unit tests are assumed complete and passing.
> **Framework:** pytest (Python). All tests in `tests/integration/`.

---

## Table of Contents

1. [Test Philosophy](#1-test-philosophy)
2. [Test Infrastructure](#2-test-infrastructure)
3. [Suite 1: TrainingLog + Storage + SerialQueue + Hooks](#3-suite-1-traininglog--storage--serialqueue--hooks)
4. [Suite 2: ResourceMeter + TrainingLog](#4-suite-2-resourcemeter--traininglog)
5. [Suite 3: BudgetAllocator + AdaptiveMultiplier + SelectionEngine](#5-suite-3-budgetallocator--adaptivemultiplier--selectionengine)
6. [Suite 4: Scheduler Facade](#6-suite-4-scheduler-facade)
7. [Suite 5: Configuration Evolution Execution Pipeline](#7-suite-5-configuration-evolution-execution-pipeline)
8. [Suite 6: Graph Emergence Execution Pipeline](#8-suite-6-graph-emergence-execution-pipeline)
9. [Suite 7: Evaluation Module](#9-suite-7-evaluation-module)
10. [Suite 8: Observability](#10-suite-8-observability)
11. [Suite 9: Full Episode Lifecycle (End-to-End)](#11-suite-9-full-episode-lifecycle-end-to-end)
12. [Cross-Cutting Concerns](#12-cross-cutting-concerns)
13. [File Layout](#13-file-layout)
14. [Execution Order and CI](#14-execution-order-and-ci)

---

## 1. Test Philosophy

### 1.1 Integration Test Boundary Principle

Each suite defines an explicit boundary: **real components below the boundary, test doubles above it.** The boundary is drawn at the integration seam being tested — the interface where two or more production components connect and exchange data.

### 1.2 What We Are Testing

Integration tests verify **cross-component interactions**:
- Data flows correctly across module boundaries (correct types, values, attribution).
- Ordering constraints are honored (e.g., admit before forward before debit).
- Side effects propagate correctly (e.g., balance depletion triggers eviction hook).
- Concurrency semantics match design (e.g., SerialQueue ordering, overdraft window).
- Error propagation crosses boundaries correctly (e.g., LLM error reaches caller, no ghost state left behind).

### 1.3 What We Are NOT Testing

- Internal logic of individual classes (covered by unit tests).
- LLM output quality or prompt engineering.
- Docker-based test execution (requires real Docker infrastructure; mocked in integration tests).
- SWE-bench issue content or real repository state.

---

## 2. Test Infrastructure

### 2.1 Shared Test Doubles

All test doubles live in `tests/integration/conftest.py` and are importable as pytest fixtures.

#### FakeLLMProvider

Implements `LLMProvider` ABC. Returns canned `LLMResponse` objects with deterministic `TokenUsage`.

Capabilities:
- **Scripted responses:** Accepts a list of `LLMResponse` objects; returns them in order per call index.
- **Error injection:** Configurable to raise network/rate-limit exceptions at specified call indices.
- **Delay injection:** Optional sleep to simulate real latency for concurrency tests.
- **Call recording:** Records every `(request, response)` pair for assertion.

```python
class FakeLLMProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse], errors: dict[int, Exception] | None = None):
        ...
    def complete(self, request: LLMRequest) -> LLMResponse:
        ...
    @property
    def call_count(self) -> int: ...
    @property
    def call_log(self) -> list[tuple[LLMRequest, LLMResponse]]: ...
```

#### InMemoryStorageBackend

Implements `StorageBackend` ABC. Backed by a plain `list[LogEntry]`. Provides identical `append()`/`query()` contract as SQLiteStorage and FileStorage, with no filesystem or database dependency.

```python
class InMemoryStorageBackend(StorageBackend):
    def __init__(self): ...
    def append(self, entry: LogEntry) -> None: ...
    def query(self, filter: LogFilter) -> list[LogEntry]: ...
    @property
    def entries(self) -> list[LogEntry]: ...
```

#### SpyHookSet

A `HookSet` implementation that records every hook invocation into an in-memory list.

```python
class SpyHookSet(HookSet):
    def __init__(self): ...
    def get_calls(self, hook_name: str) -> list[dict]: ...
    def assert_called(self, hook_name: str, times: int = 1) -> None: ...
    def assert_not_called(self, hook_name: str) -> None: ...
```

#### FakeExecutionScorer

Replaces Docker-based test execution. Returns configurable `S_exec` values per workspace.

```python
class FakeExecutionScorer(ExecutionScorer):
    def __init__(self, scores: dict[str, float]):
        """scores: workspace_id -> S_exec"""
        ...
    def score(self, patch: str, issue: Issue) -> float: ...
```

#### FakeIssue

A minimal `Issue` data object pointing at a small fixture repo (a few Python files with known bugs and tests).

#### TempDirFixture

pytest fixture providing a temporary directory tree with: fixture repo, patch output dirs, snapshot store dir, criteria cache dir. Automatically cleaned up.

#### DeterministicClock

Injectable timestamp source replacing `time.time()` to make all LogEntry timestamps deterministic and ordering assertions trivial.

```python
class DeterministicClock:
    def __init__(self, start: float = 1000.0, step: float = 1.0): ...
    def now(self) -> float: ...
```

### 2.2 Fixture Repo

A small Python project in `tests/fixtures/sample_repo/` with:
- 3-5 source files with intentional bugs.
- Corresponding test files (FAIL_TO_PASS and PASS_TO_PASS).
- A known-good patch for at least one bug.
- Used by Suite 5 (Configuration Evolution) and Suite 7 (Evaluation) for real file operations and patch generation.

---

## 3. Suite 1: TrainingLog + Storage + SerialQueue + Hooks

**File:** `tests/integration/test_training_log_storage.py`

**Components under test (real):** TrainingLog, SerialQueue, SQLiteStorage, FileStorage, HookSet.

**Mocked:** Nothing. This is the foundation — all components are production code.

**Rationale:** TrainingLog is the sole source of truth for the entire system. Every other component depends on it. Correctness here is prerequisite to all other suites.

### Test Cases

#### IT-1.1: Balance derivation across mixed operations

Execute a sequence of operations and verify balance computed from log matches expectations.

| Step | Operation | Expected Balance |
|------|-----------|-----------------|
| 1 | `record_allocate(ws1, 10000)` | 10000 |
| 2 | `record_consume(ws1, 3000)` | 7000 |
| 3 | `record_allocate(ws1, 5000)` | 12000 |
| 4 | `record_consume(ws1, 8000)` | 4000 |
| 5 | `record_consume(ws1, 5000)` | -1000 |

Assert `get_balance(ws1) == -1000`. Assert `is_active(ws1) == False`.

#### IT-1.2: Concurrent writes via SerialQueue maintain consistency

Spawn 10 threads, each submitting `record_consume(ws1, 100)` simultaneously via the SerialQueue. After all futures resolve:

- Assert `get_balance(ws1) == initial_allocation - 1000`.
- Assert exactly 10 consume LogEntry records exist.
- Assert all tx_id values are unique and monotonically increasing.

#### IT-1.3: Transfer atomicity (Graph Emergence)

```
record_allocate(agent_a, 5000)
record_allocate(agent_b, 2000)
record_transfer(agent_a, agent_b, 3000)
```

Assert: `get_balance(agent_a) == 2000`, `get_balance(agent_b) == 5000`. Verify both `from_balance_after` and `to_balance_after` on the LogEntry are correct.

#### IT-1.4: Transfer insufficient balance rejection

```
record_allocate(agent_a, 1000)
record_transfer(agent_a, agent_b, 2000) → expect error
```

Assert: no LogEntry written for the failed transfer. `get_balance(agent_a) == 1000`.

#### IT-1.5: Hook invocation ordering and completeness

Register SpyHookSet. Execute `record_allocate(ws1, 5000)` then `record_consume(ws1, 2000)`.

Assert `on_allocate` fired once with correct `to_balance_after == 5000`. Assert `on_consume` fired once with correct balance_after == 3000. Assert hook fire order matches operation order.

#### IT-1.6: on_workspace_evicted fires on balance depletion

```
record_allocate(ws1, 500)
record_consume(ws1, 600)
```

Assert `on_workspace_evicted` fired with entity_id containing ws1. Assert the hook did NOT fire for prior consume operations that left balance positive.

#### IT-1.7: Dual attribution in consume records (Graph Emergence)

```
record_consume(entity_id="agent_x", amount=500, workspace_id="ws_2")
```

Assert: `get_log_entries(filter=LogFilter(entity_id="agent_x"))` returns the entry. `get_log_entries(filter=LogFilter(workspace_id="ws_2"))` also returns it. Same record accessible through both query paths.

#### IT-1.8: Storage backend parity (SQLite vs FileStorage)

Run an identical operation sequence against both SQLiteStorage and FileStorage. Assert `query()` returns identical LogEntry lists (same field values, same ordering).

#### IT-1.9: get_log_entries filtering combinations

Populate log with diverse entries (different types, entities, workspaces, timestamps). Test all LogFilter field combinations individually and intersected: by type, entity_id, workspace_id, time range.

#### IT-1.10: Crash recovery simulation

Write entries to SQLiteStorage. Close the TrainingLog. Re-instantiate with the same storage file. Assert all entries and derived balances are intact.

---

## 4. Suite 2: ResourceMeter + TrainingLog

**File:** `tests/integration/test_resource_meter.py`

**Components under test (real):** ResourceMeter, TrainingLog (with InMemoryStorageBackend + SerialQueue).

**Mocked:** LLMProvider (FakeLLMProvider).

**Rationale:** ResourceMeter is the metered LLM gateway. Its three-phase flow (admit -> forward -> debit) integrates TrainingLog reads, external LLM calls, and TrainingLog writes. The LLM provider is mocked to isolate the meter-log interaction.

### Test Cases

#### IT-2.1: Happy path — admit, forward, debit

Allocate 10000 to ws1. Call `process(request, entity_id="ws1")`. FakeLLMProvider returns usage(input=200, output=300).

Assert: `get_balance(ws1) == 9500`. One consume LogEntry with amount=500. LLMResponse content returned correctly.

#### IT-2.2: Admission rejection (BudgetExhaustedError)

Set balance to 0 via prior consume. Call `process()`.

Assert: `BudgetExhaustedError` raised. No consume LogEntry written. FakeLLMProvider was NOT called (forward never happened).

#### IT-2.3: Free agent bypass — no admission check

Agent with balance <= 0 (Graph Emergence free agent). ResourceMeter should still forward and record consume.

Assert: FakeLLMProvider was called. Consume LogEntry written with negative resulting balance. `on_workspace_evicted` was NOT fired.

#### IT-2.4: Workspace-bound agent depletion triggers eviction

Allocate 500 to ws1. `process()` with usage=600 (overdraft / "last breath").

Assert: `on_workspace_evicted` fired. Subsequent `process()` raises `BudgetExhaustedError`.

#### IT-2.5: Dual attribution for Graph Emergence consume

Call `process(request, entity_id="agent_x", workspace_id="ws_2")`.

Assert: LogEntry has both `entity_id="agent_x"` and `workspace_id="ws_2"`. `get_balance("agent_x")` debited. Querying consume by `workspace_id="ws_2"` returns this record.

#### IT-2.6: Concurrent overdraft window

Allocate 1000. Launch two concurrent `process()` calls from the same entity, each expecting usage=700. Both should pass admission (both see balance > 0 before either debits).

After both complete: balance = 1000 - 1400 = -400. Two consume records exist. Validates the documented "allow overdraft" design.

#### IT-2.7: LLM provider error propagation

FakeLLMProvider raises a network exception. Assert: exception propagated to caller. No consume LogEntry written. Balance unchanged.

---

## 5. Suite 3: BudgetAllocator + AdaptiveMultiplier + SelectionEngine

**File:** `tests/integration/test_budget_selection.py`

**Components under test (real):** BudgetAllocator, AdaptiveMultiplier, SelectionEngine.

**Mocked:** Nothing — these are pure deterministic computations. Input data constructed directly.

**Rationale:** These three components form the Scheduler's decision brain. They interact through the eta -> allocation -> selection pipeline. No external dependencies.

### Test Cases

#### IT-3.1: Cold start allocation

No prior etas (first episode). Assert `calculate_allocation({})` returns uniform allocation of `initial_budget` per workspace.

#### IT-3.2: Eta-proportional allocation

```
workspace_scores = {ws1: 0.8, ws2: 0.2}
workspace_costs  = {ws1: 1000, ws2: 1000}
```

Assert `calculate_eta()` returns `{ws1: 0.0008, ws2: 0.0002}`. Assert `calculate_allocation()` distributes M_pool in 4:1 ratio.

#### IT-3.3: Score floor prevents zero eta

```
workspace_scores = {ws1: 0.0, ws2: 1.0}
workspace_costs  = {ws1: 500, ws2: 500}
score_floor = 0.01
```

Assert ws1 eta = `0.01 / 500 = 0.00002` (not zero). Assert ws1 receives a nonzero allocation.

#### IT-3.4: New workspace receives median eta

Three existing etas: `{ws1: 0.005, ws2: 0.010, ws3: 0.015}`. New ws4 has no prior eta.

Assert ws4 receives median value (0.010) for allocation purposes.

#### IT-3.5: SelectionEngine bottom-n eviction (config_evolution)

```
etas = {ws1: 0.1, ws2: 0.5, ws3: 0.3, ws4: 0.2}
n_evict = 1
```

Assert `evicted_ids == [ws1]`, `survivor_ids == [ws2, ws3, ws4]`.

#### IT-3.6: SelectionEngine tie-breaking is random

All etas equal: `{ws1: 0.5, ws2: 0.5, ws3: 0.5}`, n_evict=1. Run 100 times.

Assert: exactly one evicted each time. Over 100 runs, all three IDs appear at least once (randomness).

#### IT-3.7: n_evict clamping

2 workspaces, n_evict=5. Assert actual eviction count = `min(5, 2-1)` = 1. At least one workspace survives.

#### IT-3.8: Graph Emergence mode skips eviction

runtime_mode="graph_emergence". Assert `evicted_ids == []`, `survivor_ids == all`.

#### IT-3.9: AdaptiveMultiplier static mode

multiplier_mode="static", init=1.5. Call `update(eviction_rate=0.5)` multiple times. Assert `current_value` remains 1.5 always.

#### IT-3.10: AdaptiveMultiplier adaptive mode — ER tiers

Start at mult=1.0, er_target=0.1, cool_down=0.05, mult_min=0.5, mult_max=5.0.

| ER Input | Expected Behavior |
|----------|------------------|
| 0.0 | multiplier *= (1 - cool_down) = 0.95 |
| 0.05 (within dead zone: 0 < ER <= er_target) | no change |
| 0.3 | multiplier *= 1.2 |
| 0.6 | multiplier *= 1.5 |
| 1.0 | multiplier *= 2.0 |

Verify clamping at mult_min and mult_max boundaries.

#### IT-3.11: AdaptiveMultiplier dead zone

er_target=0.1. Call `update(er=0.05)`. Assert multiplier unchanged (within dead zone).

#### IT-3.12: Full pipeline — 3-episode simulation

Simulate 3 episodes sequentially:
1. Episode 1: cold start allocation.
2. Episode 2: compute etas from scores/costs, allocate proportionally, evict 1, AdaptiveMultiplier updates.
3. Episode 3: new workspace (from reproduction) gets median eta, allocate again.

Verify final state is self-consistent across all three components.

---

## 6. Suite 4: Scheduler Facade

**File:** `tests/integration/test_scheduler_facade.py`

**Components under test (real):** Scheduler, TrainingLog, ResourceMeter, SystemLLM, BudgetAllocator, AdaptiveMultiplier, SelectionEngine, WorkspaceManager, SerialQueue.

**Mocked:** LLMProvider (FakeLLMProvider for all three paths), EvaluationModule (fake returning canned EvalResults), Workspace implementations (stub ABC implementations).

**Rationale:** The Scheduler is the facade that wires all sub-components together. This suite verifies that Scheduler methods correctly orchestrate sub-components and that callback factories produce working callbacks.

### Test Cases

#### IT-4.1: allocate_budgets() cold start

Create Scheduler with 3 workspace stubs. Call `allocate_budgets()`.

Assert: TrainingLog has 3 allocate records, each with amount=initial_budget. Each workspace's `receive_budget()` was called with the correct amount.

#### IT-4.2: allocate_budgets() subsequent episode

Pre-populate TrainingLog with prior episode data (allocate + consume records). Call `allocate_budgets()`.

Assert: new allocate records have amounts proportional to etas derived from prior episode's scores and costs.

#### IT-4.3: evaluate_and_select()

Provide patches dict. Fake EvaluationModule returns known scores.

Assert: (a) C_period_w aggregated correctly from TrainingLog consume records, (b) etas computed correctly, (c) evicted_ids and survivor_ids returned correctly, (d) eval_results forwarded intact.

#### IT-4.4: get_metered_llm_callback() produces working callback

Get callback for ws1. Invoke it with an LLMRequest.

Assert: ResourceMeter.process() was invoked. Consume record in TrainingLog has correct workspace_id=ws1.

#### IT-4.5: get_system_llm_callback() produces unmetered callback

Get callback. Invoke it.

Assert: FakeLLMProvider was called. NO consume record written to TrainingLog.

#### IT-4.6: replace_evicted() creates new workspaces

Mark ws1 as evicted. Provide new config. Call `replace_evicted([new_config])`.

Assert: new workspace appears in `get_workspaces()`. Old ws1 no longer present. Total workspace count preserved.

#### IT-4.7: Callback identity isolation

Get metered callbacks for ws1 and ws2 respectively. Call ws1's callback, then ws2's callback.

Assert: consume records correctly attributed — ws1's consume to ws1, ws2's to ws2. No cross-contamination.

#### IT-4.8: get_balance() delegates to TrainingLog

Perform allocate + consume operations through Scheduler methods. Call `get_balance(entity_id)`.

Assert: result matches `TrainingLog.get_balance()`.

---

## 7. Suite 5: Configuration Evolution Execution Pipeline

**File:** `tests/integration/test_config_evolution.py`

**Components under test (real):** ConfigEvolutionWorkspace, DAGExecutor, ReactAgent, ActionRegistry, file operation Actions (ReadFileAction, EditFileAction, BashAction, SearchCodeAction, FindFilesAction).

**Mocked:** LLMProvider (FakeLLMProvider returning deterministic tool_calls), ConfigMutator (spy recording calls), ConfigSnapshotStore (spy), SystemLLM callback (FakeLLMProvider).

**Rationale:** Tests the Configuration Evolution execution pipeline end-to-end: YAML config parsed -> DAG executed -> ReactAgent per step -> Actions invoked on fixture repo -> patch produced. LLM is mocked to control agent decisions; Actions execute for real.

### Test Cases

#### IT-5.1: Single-step DAG execution

Config with one step (id="fix", tools=["read_file", "edit_file"]). FakeLLMProvider scripted to: (1) return tool_call for read_file, (2) return tool_call for edit_file, (3) return text response (no more actions).

Assert: execution completes. Target file in fixture repo was actually modified.

#### IT-5.2: Multi-step DAG with dependencies

Config: step "locate" (tools=[search_code, find_files]) -> step "fix" (tools=[edit_file, bash], inputs=[locate]).

Assert: locate's output is injected into fix's context. Fix step receives the context string containing locate's findings (verify context injection).

#### IT-5.3: DAG step failure aborts pipeline

FakeLLMProvider for step 1 raises BudgetExhaustedError.

Assert: DAGExecutor returns `ExecutionResult(aborted=True, abort_step="step1")`. Step 2 never executed (FakeLLMProvider call_count for step 2 is 0).

#### IT-5.4: Cyclic DAG detection

Config: step A depends on B, step B depends on A.

Assert: `CyclicDependencyError` raised before any execution begins.

#### IT-5.5: submit_patch persists to correct path

After successful execute, call `submit_patch()`.

Assert: file exists at `{output_dir}/{workspace_id}/{episode_id}.patch`. Content is non-empty.

#### IT-5.6: submit_patch on aborted DAG produces empty/partial patch

Execute with a failing DAG (step 1 fails). Call `submit_patch()`.

Assert: patch file exists at the correct path (may be empty or partial).

#### IT-5.7: post_episode — surviving workspace calls self_rewrite

Provide eval_results indicating this workspace survived selection.

Assert: (a) system_llm callback invoked (for experience summary generation), (b) ConfigMutator.self_rewrite() called with current config + generated summary, (c) ConfigSnapshotStore.save() called with correct snapshot fields.

#### IT-5.8: post_episode — evicted workspace calls reproduce

Provide eval_results indicating this workspace was evicted. Provide best config reference.

Assert: (a) ConfigMutator.reproduce() called with best config + summaries, (b) return value is a new config dict (not None).

#### IT-5.9: Action subset filtering

StepConfig has `tools=["bash", "read_file"]`.

Assert: ReactAgent receives exactly those 2 actions. edit_file, write_file, etc. are not available to the agent.

#### IT-5.10: ReactAgent iteration limit

Set max_iterations=3. FakeLLMProvider always returns a non-terminal tool_call.

Assert: agent terminates after 3 iterations with `termination_reason="max_iterations"`.

---

## 8. Suite 6: Graph Emergence Execution Pipeline

**File:** `tests/integration/test_graph_emergence.py`

**Components under test (real):** GraphEmergenceWorkspace, PlanExecuteAgent, FreeAgentManager, PricingEngine, Session, Agent, Soul, Skill, DelegateTaskAction, ReportResultAction.

**Mocked:** LLMProvider (FakeLLMProvider for metered and system paths), TrainingLog (real with InMemoryStorageBackend), SkillReviewer (spy), embedding computation (fake returning fixed vectors).

**Rationale:** Tests the Graph Emergence execution pipeline: responsible agent -> Plan->Execute loop -> DelegateTaskAction discovers candidates -> hires free agent -> free agent works in isolated session -> ReportResultAction returns result.

### Test Cases

#### IT-6.1: Responsible agent Plan->Execute basic flow

FakeLLMProvider scripted: planning phase returns a plan text, execution phase returns tool calls, then task_done.

Assert: PlanExecuteAgent completes. market_info_provider callback was invoked during planning phase.

#### IT-6.2: DelegateTaskAction returns candidate list

Register 3 free agents with skills and fixed embedding vectors. Call `DelegateTaskAction.execute(task_description="fix parsing bug")`.

Assert: returns formatted candidate list containing agent_ids, skill descriptions, and prices. Candidates ordered by relevance then price.

#### IT-6.3: PricingEngine price calculation with debt premium

Register agent_x. Record several consume entries in TrainingLog for agent_x (establishing history).

Assert: `calculate_price(agent_x) == weighted_avg_cost * buffer_multiplier`.

Then drive balance negative. Assert: price includes `debt_premium = max(0, -balance)`.

#### IT-6.4: Session isolation across workspaces

Create sessions for agent_x in ws1 and ws2. Add messages to ws1's session.

Assert: ws2's session has zero messages. `get_messages()` returns only ws1's history for ws1 session.

#### IT-6.5: Session compaction triggers near context limit

Create session with max_context_tokens=100. Add messages until approaching the threshold.

Assert: system_llm callback was called (for compaction). conversation_history compressed (fewer messages, contains summary).

#### IT-6.6: ReportResultAction delivers result

Set up a report callback spy. Call `ReportResultAction.execute(result="fix applied", status="success")`.

Assert: callback invoked with correct result text and status.

#### IT-6.7: Free agent no-eviction semantics

Free agent's balance goes negative via consume records.

Assert: `is_active()` returns True (free agents never evict). No `on_workspace_evicted` hook fired.

#### IT-6.8: post_episode triggers SkillReviewer

Call `post_episode(eval_results)`.

Assert: SkillReviewer.review() called with eval_results. Return value is None (Graph Emergence never returns new configs via post_episode).

#### IT-6.9: receive_budget flows to responsible agent

Call `receive_budget(5000)`.

Assert: TrainingLog shows allocate record for responsible agent_id. Derived balance increased by 5000.

#### IT-6.10: End-to-end hiring flow

Full delegate -> hire -> execute -> report cycle with scripted FakeLLMProvider:
1. Responsible agent calls delegate_task.
2. DelegateTaskAction returns candidates.
3. Scripted LLM picks a candidate.
4. System executes transfer (hire).
5. Free agent executes in isolated session.
6. Free agent calls report_result.

Verify: (a) transfer record in TrainingLog, (b) free agent's consume records have correct workspace_id attribution, (c) responsible agent receives the reported result.

---

## 9. Suite 7: Evaluation Module

**File:** `tests/integration/test_evaluation_module.py`

**Components under test (real):** EvaluationModule, LLMJudge, CriteriaCache.

**Mocked:** ExecutionScorer (FakeExecutionScorer), LLMProvider for judge (FakeLLMProvider returning scripted criteria and evaluation JSON).

**Rationale:** Tests the two-phase scoring pipeline: S_exec (from fake) + S_llm (from LLMJudge + CriteriaCache with fake LLM). Docker-based ExecutionScorer is replaced but LLMJudge and CriteriaCache interact for real.

### Test Cases

#### IT-7.1: S_exec = 1.0 skips LLMJudge

FakeExecutionScorer returns 1.0 for ws1. Call `evaluate_all()`.

Assert: LLMJudge was NOT invoked (FakeLLMProvider call_count == 0). `S_w == 1.0`.

#### IT-7.2: S_exec < 1.0 triggers LLMJudge

FakeExecutionScorer returns 0.5. FakeLLMProvider returns criteria JSON (step 1) then evaluation JSON with mean score 7/10 (step 2).

Assert: `S_w = 0.5 + (1-0.5) * 0.3 * 0.7 = 0.605`.

#### IT-7.3: S_exec = 0.0 — LLM contribution capped by beta

FakeExecutionScorer returns 0.0. FakeLLMProvider returns S_llm = 1.0.

Assert: `S_w = 0.0 + 1.0 * 0.3 * 1.0 = 0.3`. Verifies LLM signal never dominates.

#### IT-7.4: CriteriaCache hit avoids re-extraction

Evaluate ws1 on issue_1 (criteria extracted via LLM). Then evaluate ws2 on the same issue_1.

Assert: criteria extraction LLM call happened exactly once (cache hit on second). Both evaluations used the same criteria.

#### IT-7.5: CriteriaCache persistence across instances

Extract criteria and write to disk via CriteriaCache. Create a new CriteriaCache instance pointing at the same directory.

Assert: cache hit without LLM call.

#### IT-7.6: beta=0 produces pure execution score

Set beta=0. FakeExecutionScorer returns 0.5.

Assert: `S_w == 0.5`. LLMJudge NOT called.

#### IT-7.7: No patch submitted yields S_w = 0

Call `evaluate_all()` with missing patch for ws1.

Assert: `S_w == 0` for ws1. Neither ExecutionScorer nor LLMJudge invoked for ws1.

#### IT-7.8: Batch evaluation of multiple workspaces

4 workspaces with varying S_exec (1.0, 0.5, 0.0, no patch).

Assert: evaluate_all returns correct EvalResult for each. LLMJudge called only for S_exec < 1.0 workspaces that submitted patches.

---

## 10. Suite 8: Observability

**File:** `tests/integration/test_observability.py`

**Components under test (real):** Observer, TrainingLog (with InMemoryStorageBackend), HookSet wiring.

**Mocked:** None for the core path. TempDir for output.

**Rationale:** Observer is a pure consumer receiving events via hooks. Tests verify the full chain: TrainingLog operation -> hook fires -> Observer receives event -> Observer produces output.

### Test Cases

#### IT-8.1: Observer receives allocation events

Execute 3 allocations. Assert: Observer recorded 3 on_allocate calls with correct amounts and balances.

#### IT-8.2: Observer receives consume with dual attribution

Execute consume with `agent_id != workspace_id`. Assert: Observer's on_consume receives both entity_id and workspace_id correctly.

#### IT-8.3: Observer receives eviction event

Deplete a workspace's budget via consume. Assert: Observer's on_workspace_evicted fires. `print_episode_summary()` includes the evicted workspace.

#### IT-8.4: export_trends produces output file

Execute a multi-episode simulation (allocate, consume, repeat). Call `export_trends()`.

Assert: output file exists in output_dir. Contains expected data structure (parseable, non-empty).

#### IT-8.5: Hook exception does not corrupt TrainingLog

Inject an Observer whose on_consume raises an exception. Execute a consume.

Assert: (a) LogEntry was still written to storage (write completed before hook), (b) exception propagates to the caller.

---

## 11. Suite 9: Full Episode Lifecycle (End-to-End)

**File:** `tests/integration/test_full_episode.py`

**Components under test (real):** `run_training()`, Scheduler (full assembly), WorkspaceManager, ConfigEvolutionWorkspace (or workspace stubs), TrainingLog, ResourceMeter, SystemLLM, BudgetAllocator, AdaptiveMultiplier, SelectionEngine, Observer.

**Mocked:** LLMProvider (FakeLLMProvider for all three paths), ExecutionScorer (FakeExecutionScorer).

**Rationale:** Highest-level integration test. Runs `run_training()` with a minimal issue source (1-2 issues), verifying the full episode lifecycle end-to-end.

### Test Cases

#### IT-9.1: Single episode — Configuration Evolution, 3 workspaces

Run one episode with 3 ConfigEvolution workspaces.

Assert:
1. 3 allocate records in TrainingLog (cold start).
2. All 3 workspaces executed (execute() called on each).
3. 3 patches submitted to disk.
4. EvaluationModule produced 3 EvalResults.
5. 1 workspace evicted (n_evict=1).
6. post_episode produced 1 new config (from evicted workspace's reproduction).
7. replace_evicted created 1 new workspace.
8. Final workspace count is still 3.

#### IT-9.2: Two consecutive episodes — config evolution

Run 2 episodes sequentially.

Assert:
1. Second episode allocation uses etas computed from episode 1.
2. New workspace (from episode 1 eviction) receives median eta.
3. AdaptiveMultiplier updated between episodes.
4. ConfigSnapshotStore has snapshots for both episodes (all workspaces).

#### IT-9.3: Single episode — Graph Emergence, 2 workspaces

Run one episode with 2 GraphEmergence workspaces.

Assert:
1. No eviction by SelectionEngine (graph_emergence skips bottom-n).
2. post_episode calls SkillReviewer.
3. All consume records in TrainingLog have workspace_id attribution.

#### IT-9.4: Budget exhaustion mid-episode

Set initial_budget very low. FakeLLMProvider returns large token usage per call.

Assert:
1. Workspace receives BudgetExhaustedError during execute.
2. `on_workspace_evicted` fires.
3. Evaluation assigns S_exec=0 for empty/partial patch.
4. Evicted workspace still participates in post_episode (reproduction).

#### IT-9.5: Observer captures complete episode lifecycle

Wire Observer via SpyHookSet. Run one episode.

Assert: event sequence recorded by Observer matches expected order: `on_allocate (x3)` -> `on_consume (various)` -> `[on_workspace_evicted if any]` -> post-episode effects visible.

#### IT-9.6: Phase ordering invariant

Instrument workspace stubs to record method call timestamps. Run one episode.

Assert strict ordering: `receive_budget` < `execute` < `submit_patch` < `evaluate_and_select completes` < `post_episode` < `replace_evicted`.

---

## 12. Cross-Cutting Concerns

These concerns are woven into the suites above but called out explicitly for review coverage.

### 12.1 Concurrency (Suites 1, 2, 4)

- Multiple workspaces calling ResourceMeter concurrently via independent callbacks.
- SerialQueue ordering guarantees under parallel thread load.
- The documented "overdraft window" between admit and debit phases (IT-2.6).

### 12.2 Error Propagation (Suites 2, 5, 6, 7)

- LLMProvider network errors bubble correctly through ResourceMeter (IT-2.7).
- DAG step failure propagates through DAGExecutor to ConfigEvolutionWorkspace (IT-5.3).
- BudgetExhaustedError terminates the correct workspace without affecting parallel workspaces (IT-9.4).

### 12.3 Data Integrity Invariants (assertions in every suite)

These invariants should be checked as post-conditions in relevant test cases:

1. **Balance conservation:** Sum of all allocate amounts - sum of all consume amounts - sum of all outgoing transfers + sum of all incoming transfers == sum of all entity balances at any point.
2. **Graph Emergence consume attribution:** Every consume LogEntry in Graph Emergence mode has a non-null workspace_id.
3. **Append-only invariant:** TrainingLog entry count never decreases within a test.

---

## 13. File Layout

```
tests/
├── integration/
│   ├── conftest.py                     # Shared fixtures: FakeLLMProvider, InMemoryStorageBackend,
│   │                                   #   SpyHookSet, FakeExecutionScorer, FakeIssue,
│   │                                   #   TempDirFixture, DeterministicClock
│   ├── test_training_log_storage.py    # Suite 1: TrainingLog + Storage + SerialQueue + Hooks
│   ├── test_resource_meter.py          # Suite 2: ResourceMeter + TrainingLog
│   ├── test_budget_selection.py        # Suite 3: BudgetAllocator + AdaptiveMultiplier + SelectionEngine
│   ├── test_scheduler_facade.py        # Suite 4: Scheduler Facade
│   ├── test_config_evolution.py        # Suite 5: Configuration Evolution Pipeline
│   ├── test_graph_emergence.py         # Suite 6: Graph Emergence Pipeline
│   ├── test_evaluation_module.py       # Suite 7: Evaluation Module
│   ├── test_observability.py           # Suite 8: Observability
│   └── test_full_episode.py            # Suite 9: Full Episode Lifecycle
├── fixtures/
│   └── sample_repo/                    # Small Python project with intentional bugs and tests
│       ├── src/
│       │   └── ...                     # 3-5 source files with known bugs
│       ├── tests/
│       │   └── ...                     # FAIL_TO_PASS and PASS_TO_PASS tests
│       └── patches/
│           └── ...                     # Known-good patches for fixture bugs
└── test_plan.md                        # This document
```

---

## 14. Execution Order and CI

### 14.1 Dependency Order

Suites should run in dependency order. Later suites depend on the integration boundaries validated by earlier suites:

```
Suite 1 (TrainingLog foundation)
  └─> Suite 2 (ResourceMeter + TrainingLog)
  └─> Suite 3 (BudgetAllocator + SelectionEngine, pure computation)
        └─> Suite 4 (Scheduler facade, wires everything)
              ├─> Suite 5 (ConfigEvolution pipeline)
              ├─> Suite 6 (GraphEmergence pipeline)
              ├─> Suite 7 (Evaluation pipeline)
              └─> Suite 8 (Observability)
                    └─> Suite 9 (Full episode E2E)
```

### 14.2 pytest Markers

Each suite is tagged with a pytest marker for selective execution:

```python
# conftest.py or pyproject.toml
markers = [
    "integration",           # All integration tests
    "suite_1_training_log",
    "suite_2_resource_meter",
    "suite_3_budget_selection",
    "suite_4_scheduler",
    "suite_5_config_evolution",
    "suite_6_graph_emergence",
    "suite_7_evaluation",
    "suite_8_observability",
    "suite_9_full_episode",
]
```

### 14.3 CI Configuration

```bash
# Run all integration tests in dependency order
pytest tests/integration/ -v --tb=short -x

# Run a specific suite
pytest tests/integration/ -m suite_1_training_log -v

# Run suites 5-8 in parallel (independent of each other)
pytest tests/integration/ -m "suite_5_config_evolution or suite_6_graph_emergence or suite_7_evaluation or suite_8_observability" -v -n auto
```

### 14.4 Estimated Test Count

| Suite | Test Cases | Estimated Runtime |
|-------|-----------|-------------------|
| 1. TrainingLog + Storage | 10 | < 5s |
| 2. ResourceMeter | 7 | < 3s |
| 3. Budget + Selection | 12 | < 2s |
| 4. Scheduler Facade | 8 | < 5s |
| 5. Config Evolution | 10 | < 10s |
| 6. Graph Emergence | 10 | < 10s |
| 7. Evaluation Module | 8 | < 5s |
| 8. Observability | 5 | < 3s |
| 9. Full Episode E2E | 6 | < 15s |
| **Total** | **76** | **< 60s** |

All timings assume FakeLLMProvider with zero latency. No Docker, no network calls, no real LLM inference.
