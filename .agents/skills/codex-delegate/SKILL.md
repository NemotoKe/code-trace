---
name: codex-cli-delegation
description: Delegate independently evaluable, bounded implementation tasks to Codex CLI using gpt-5.6-luna with xhigh reasoning, while the outer agent owns repository inspection, task decomposition, acceptance criteria, diff review, and independent verification. Use when the user explicitly asks to delegate implementation to Codex CLI.
---

# Codex CLI delegation

You are the orchestrator. Codex CLI is the implementation worker.

You define the task, inspect the result, and verify it independently. Do not
silently implement or repair Codex's changes yourself.

## Before delegation

1. Confirm Codex is available:

   ```bash
   command -v codex
   codex --version
   codex login status
   ```

   If unavailable, stop and tell the user.

2. Inspect the repository enough to make the delegated task self-contained.
   Codex has no context from this conversation.

3. Split the request into the smallest coherent units that can be evaluated
   independently. Each unit should have one primary observable outcome, its
   own acceptance criteria, and its own relevant tests or checks.

4. Define explicit acceptance criteria before delegation.

## Build the delegated task

Before writing or sending each implementation task, use the
`break-down-task-creator` skill to turn that task unit into a concise,
self-contained implementation prompt. Treat its output as the task body and
preserve its objective, requirements, constraints, acceptance criteria, TDD
scenarios, and non-goals.

Do not combine unrelated outcomes into one delegation. If units depend on one
another, state the dependency and delegate them in order; still give each unit
an independently verifiable completion condition. Send only one unit in each
Codex invocation. Add only Codex-specific invocation details around the prompt.

## Delegate

Run Codex from the repository root with `codex exec`.

```bash
cat <<'EOF' | codex exec \
  --sandbox workspace-write \
  --json \
  -m gpt-5.6-luna \
  -c model_reasoning_effort=xhigh \
  -
<SELF-CONTAINED TASK>
EOF
```

Include:

* Objective
* Relevant background and paths
* Acceptance criteria
* Allowed scope
* Required tests
* Non-goals

Keep the task bounded. Do not delegate vague requests such as "implement this
feature."

Capture the session/thread ID from the JSON output for corrective passes.

## Per-unit execution loop

Process implementation units in dependency order. Do not start the next unit
until the current unit passes all post-unit checks.

For each implementation unit:

1. Delegate the implementation prompt generated from
   `break-down-task-creator` to `gpt-5.6-luna` with xhigh reasoning. When
   using the repository-local copy, read
   `skills/break-down-task-creator/SKILL.md` first.
2. After the implementation worker finishes, start a separate Luna xhigh
   invocation using the `integration-test-builder` skill (read
   `skills/integration-test-builder/SKILL.md` when using the repository-local
   copy). Give it only the current unit's requirements, acceptance criteria,
   changed files, and relevant test results. Have it add or improve
   independently executable integration tests and run them.
3. After the integration-test-builder task finishes, start another separate
   Luna xhigh invocation using the `integration-reviewer` skill (read
   `skills/integration-reviewer/SKILL.md` when using the repository-local
   copy). Ask it to inspect the current unit and return the skill's
   evidence-based PASS or FAIL verdict. Use a fresh session so the review is
   not based on the implementer's conclusions.
4. Mark the unit complete only when its acceptance criteria are satisfied, the
   relevant tests pass, and the integration reviewer returns PASS.
5. If implementation, integration testing, or review fails, send a bounded
   corrective task to Luna, then repeat the post-unit checks before continuing.

Keep implementation, integration-test-builder, and integration-reviewer work
as separate Codex invocations. Apply this loop to each implementation unit;
do not recursively apply it to the test-builder or reviewer tasks themselves.

## Model and reasoning effort

Use `gpt-5.6-luna` with `model_reasoning_effort=xhigh` for every delegated task,
including corrective passes and verification work performed by Codex.

Do not silently switch to Terra, Sol, a lower reasoning effort, or Ultra. Ultra
may introduce Codex-managed subagents, which duplicates the outer orchestrator
role. If Luna or xhigh is unavailable, stop and report the blocker instead of
downgrading the task.

## Review and verify

After Codex finishes:

```bash
git status --short
git diff --stat
git diff
```

Review:

* correctness
* acceptance criteria
* scope creep
* test quality
* security implications
* unrelated edits

Run relevant tests yourself when possible. Do not accept the change solely
because Codex reports success.

## Corrective pass

If the implementation is wrong or incomplete, send a precise correction to the
same session instead of fixing it yourself:

```bash
cat <<'EOF' | codex exec resume \
  <SESSION_ID> \
  --json \
  -m gpt-5.6-luna \
  -c model_reasoning_effort=xhigh \
  -
Defect:
<WHAT IS WRONG>

Evidence:
<DIFF / TEST FAILURE / BEHAVIOR>

Required correction:
<BOUNDED FIX>

Preserve already-satisfied acceptance criteria.
Do not expand scope.
Run the relevant tests again.
EOF
```

Then review the diff and verify again.

## Responsibility boundary

The orchestrator owns task definition, scope, acceptance criteria, model
selection, review, and verification.

Codex owns source edits, tests, implementation-level execution, and corrective
changes.

## Final report

Tell the user:

* what changed
* which model/mode was used
* what you independently verified
* whether acceptance criteria passed
* anything still unresolved

This skill applies only to the current explicitly delegated task.
