---
name: break-down-task-creator
description: Transform rough engineering tasks into concise, self-contained implementation prompts for coding agents or subagents, with strict Test-Driven Development as the required implementation process.
---

# Break Down Task Creator

## Purpose

Transform a rough engineering task into a high-signal, self-contained implementation prompt for a coding agent or subagent.

Keep the prompt independent of any particular model, provider, CLI, or reasoning
mode. The caller may add worker-specific invocation details after generating the
prompt, but the task itself must remain portable across implementation agents.

The generated prompt must drive implementation using Test-Driven Development (TDD).

## Core Principles

### 1. Outcome over implementation

Specify:

- desired behavior
- constraints
- invariants
- acceptance criteria

Do not prescribe implementation details unless they are actual requirements.

### 2. Repository first

Before making changes, inspect the relevant production code, existing tests, conventions, and abstractions.

Prefer the repository's existing design unless it conflicts with the requested behavior.

### 3. TDD is the implementation process

All behavioral changes must follow:

1. **Red** — add or modify a test that expresses the required behavior and verify that it fails for the expected reason.
2. **Green** — make the smallest production-code change necessary to make the test pass.
3. **Refactor** — improve the implementation while keeping all tests green.

Do not implement production behavior first and add tests afterward.

For bugs, first reproduce the bug with a failing regression test.

For refactoring tasks, establish characterization tests when existing behavior is insufficiently protected.

If a meaningful automated test cannot reasonably be written, explain why before making the implementation change.

### 4. Small increments

Prefer multiple small Red → Green cycles over implementing the entire task before running tests.

Each cycle should introduce one coherent behavior.

### 5. Preserve behavior outside scope

Existing behavior outside the task must remain unchanged.

Do not perform unrelated refactoring.

---

## Prompt Structure

### Objective

Describe the desired end state in 1–3 sentences.

### Context

Include only repository or domain context that materially affects implementation.

### Requirements

List the required observable behavior.

### Constraints

Specify invariants and boundaries such as:

- preserve public APIs
- maintain backward compatibility
- avoid new dependencies
- preserve unrelated behavior

### Acceptance Criteria

Define independently verifiable completion conditions.

### TDD Scenarios

Translate the acceptance criteria into behavioral scenarios to drive implementation.

Focus on:

- normal behavior
- boundary conditions
- regression cases
- important failure paths

Do not prescribe exact test code unless necessary.

### Non-goals

Explicitly identify adjacent work that should not be performed when useful.

---

## Implementation Instructions

Inspect the relevant repository code and existing tests before changing anything.

Implement the task using strict TDD.

For each behavioral increment:

1. Add or modify the smallest test that captures the next required behavior.
2. Run it and confirm it fails for the expected reason.
3. Change production code minimally until the test passes.
4. Run the relevant test suite.
5. Refactor only while tests remain green.
6. Continue with the next behavior.

Do not:

- write the complete production implementation before tests
- weaken assertions merely to make tests pass
- change existing tests to accommodate incorrect behavior
- mock away the behavior being tested
- perform unrelated cleanup

Reuse existing test conventions, helpers, fixtures, and abstractions where appropriate.

If repository evidence contradicts an assumption in the prompt, follow the repository's actual design while preserving the requested behavior.

## Completion Report

At completion, report:

- changed files
- implemented behavior
- Red → Green cycles performed
- tests added or changed
- tests/checks executed
- relevant design decisions
- unresolved issues

## Output Rules

Return only the implementation prompt.

Keep it concise and execution-oriented.

Include information that constrains correctness, not information the implementation agent can cheaply discover itself.
