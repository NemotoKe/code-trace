---
name: codex-cli-delegation
description: Delegate independently evaluable, bounded implementation tasks to Codex CLI using gpt-5.6-luna with max reasoning, while the outer agent owns repository inspection, task decomposition, acceptance criteria, diff review, independent verification, and mutation testing. Use when the user explicitly asks to delegate implementation to Codex CLI.
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

Before writing or sending each task, use the `break-down-task-creator` skill to
turn that unit into a concise, self-contained prompt. Treat its output as the
task body and preserve its objective, requirements, constraints, acceptance
criteria, TDD scenarios, and non-goals.

This applies to **every** delegation, not only implementation ones. A
test-building or review task written as a loose request produces loose work; the
same structure — contract as concrete cases, explicit scope, explicit non-goals,
required verification — is what makes any of them checkable.

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

**Read `references/writing-prompts.md` before writing the prompt.** It carries
the rules that decide whether a delegation lands, each tied to something that
measurably went wrong or right here — write requirements as inputs with expected
outputs rather than as principles, paste data instead of describing it,
constrain where an answer may live and not only what it must do, verify expected
numbers before asserting them, and name the files that may and may not change.

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
   repository-local copy). **Write its prompt with the same discipline as an
   implementation prompt** — state the contract as concrete cases with expected
   results, name the boundaries to cross, and say what is already covered so it
   does not re-tread. A vague "add integration tests" produces tests that
   restate the implementation.
4. **Run mutation testing yourself.** This is the gate, not the reviewer.
   See "Mutation testing" below.
5. Run the `integration-reviewer` skill (read
   `skills/integration-reviewer/SKILL.md` when using the repository-local copy)
   in a fresh Luna max session — but only where a wrong answer propagates:
   data other units will build on, a schema, a resolver whose output becomes
   edges. Skip it for thin wrappers over an already-reviewed layer.
6. Mark the capability complete when its acceptance criteria are satisfied, the
   tests pass, and the mutants are caught.
7. If any step fails, send a bounded corrective task to Luna, then repeat the
   checks before continuing.

Steps 1 and 2 run per implementation unit. Steps 3 to 5 run **per capability**,
not per unit: once units are small enough to review individually, running the
integration skills against each one costs more round trips than it detects.

Triage every reviewer finding against the original requirements before acting
on one. Reviewers report defects that the prompt authorised, and they miss
defects the prompt never mentioned.

Keep implementation, integration-test-builder, and integration-reviewer work
as separate Codex invocations. Apply this loop to each implementation unit;
do not recursively apply it to the test-builder or reviewer tasks themselves.

## Mutation testing

A passing suite proves nothing on its own — the tests and the code were usually
written by the same worker. Break the implementation on purpose and check the
suite notices.

```bash
git worktree add <scratch> HEAD        # never mutate the working tree
cp <uncommitted files> <scratch>/...   # the work under test is usually uncommitted
cd <scratch> && git add -A && git commit -m baseline
```

**Commit that baseline inside the scratch worktree.** The revert between mutations
is `git checkout -- .`, which otherwise throws away the very files you copied in
and silently leaves every mutation reporting "anchor not found".

Then apply one mutation, run the suite, revert, repeat. Target the decisions the contract names: traversal order, rule
precedence, a filter's comparison operator, what goes in a denominator, which
clause is parsed.

Read every survivor before reporting it, and prove it non-equivalent by running
the mutated code on a concrete input and showing the output differs. **An
equivalent mutant changes no behaviour and is not a test gap** — a dedupe over
already-unique keys, or a guard the caller already guarantees. Three of thirteen
mutants on this repository were equivalent, one of them because the mutation
itself was a syntactic no-op. Reporting those as gaps would have sent a worker
to write tests for nothing. Where a guard is redundant only because of what
upstream happens to do today, say so: nothing protects it if upstream changes.

This is cheap and it is the highest-yield check available. On the type-hierarchy
capability it produced the only genuine finding, while the test-builder found
none and the reviewer's earlier findings included one false positive and one
miss.

## Re-measuring on a large corpus

Verifying against a big real repository is worth it, but do not re-index it for
every unit. Re-index only when the index content can actually have changed —
extraction, resolution, or persistence. A query-layer or CLI unit reuses the
existing index. When behaviour should be unchanged, compare table hashes
against the previous index rather than re-reading the numbers by eye.

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
