---
name: codex-cli-delegation
description: Delegate independently evaluable, bounded implementation tasks to Codex CLI using gpt-5.6-luna with max reasoning, while the outer agent owns repository inspection, task decomposition, acceptance criteria, diff review, and independent verification. Use when the user explicitly asks to delegate implementation to Codex CLI.
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

## How small

Task size itself degrades output quality. This is a capability limit, not
something a better-worded prompt recovers. Splitting further is the only
reliable lever.

Aim for **one function-level behavior per delegation, at most three acceptance
criteria**. "One reviewable capability" is still too big — split a capability
again into extract / resolve / persist / query.

Never mix new schema design with new logic in the same delegation.

The lower bound on splitting is **a size the human can review each time**. Do
not batch units to save round trips or cost; round trips are cheap and a
delegation that lands wrong costs far more.

Observed on this repository: a delegation with 14 acceptance criteria silently
dropped two instructions; narrowing to 6 still produced a defect affecting
22,000 records; at 3 criteria the results have been clean.

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
  -c model_reasoning_effort=max \
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

Write every requirement as a concrete example with its expected output, not as
a principle. Abstract constraints are the ones that get dropped. "Preserve the
explanatory comments" was ignored; "this input must not produce this symbol"
was not. Where a list is data rather than logic, paste the list into the prompt
instead of describing it.

Never judge a background run by its exit code — a redirect makes a failed
invocation exit 0. Read stderr, and read the final agent message.

Capture the session/thread ID from the JSON output for corrective passes.

## Per-unit execution loop

Process implementation units in dependency order. Do not start the next unit
until the current unit passes all post-unit checks.

For each implementation unit:

1. Delegate the implementation prompt generated from
   `break-down-task-creator` to `gpt-5.6-luna` with max reasoning. When
   using the repository-local copy, read
   `skills/break-down-task-creator/SKILL.md` first.
2. Verify the unit yourself before anything else runs. Execute each acceptance
   criterion independently rather than reading the completion report — the
   report is silent about instructions that were dropped. Add cases the prompt
   did not name, to catch both over- and under-reach.
3. Once the units that make up one user-visible capability are all in, start a
   separate Luna max invocation using the `integration-test-builder` skill
   (read `skills/integration-test-builder/SKILL.md` when using the
   repository-local copy). Give it the capability's requirements, acceptance
   criteria, changed files, and relevant test results. Have it add or improve
   independently executable integration tests and run them.
4. After the integration-test-builder task finishes, start another separate
   Luna max invocation using the `integration-reviewer` skill (read
   `skills/integration-reviewer/SKILL.md` when using the repository-local
   copy). Ask it to inspect the capability and return the skill's
   evidence-based PASS or FAIL verdict. Use a fresh session so the review is
   not based on the implementer's conclusions.
5. Mark the capability complete only when its acceptance criteria are
   satisfied, the relevant tests pass, and the integration reviewer returns
   PASS.
6. If implementation, integration testing, or review fails, send a bounded
   corrective task to Luna, then repeat the post-unit checks before continuing.

Steps 1 and 2 run per implementation unit. Steps 3 and 4 run **per capability**,
not per unit: once units are small enough to review individually, running the
integration skills against each one costs more round trips than it detects.

Triage every reviewer finding against the original requirements before acting
on one. Reviewers report defects that the prompt authorised, and they miss
defects the prompt never mentioned.

Keep implementation, integration-test-builder, and integration-reviewer work
as separate Codex invocations. Apply this loop to each implementation unit;
do not recursively apply it to the test-builder or reviewer tasks themselves.

## Model and reasoning effort

Use `gpt-5.6-luna` with `model_reasoning_effort=max` for every delegated task,
including corrective passes and verification work performed by Codex.

Do not silently switch to Terra, Sol, a lower reasoning effort, or Ultra. Ultra
may introduce Codex-managed subagents, which duplicates the outer orchestrator
role. If Luna or max is unavailable, stop and report the blocker instead of
downgrading the task.

Reasoning effort is not a substitute for splitting the task. Raising it does not
rescue a delegation that is too large; see "How small" above.

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

`codex exec resume` does **not** accept `--sandbox`. Copying that flag over from
the `codex exec` block above makes the invocation exit immediately, and through
a pipeline the exit code still reads 0 — the corrective pass looks sent and is
not. Pass the sandbox as `-c sandbox_mode=workspace-write`, and confirm the run
by reading stderr and the final agent message.

```bash
cat <<'EOF' | codex exec resume \
  <SESSION_ID> \
  --json \
  -m gpt-5.6-luna \
  -c model_reasoning_effort=max \
  -c sandbox_mode=workspace-write \
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
