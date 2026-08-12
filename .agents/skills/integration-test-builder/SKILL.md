---
name: integration-test-builder
description: Build requirement-driven integration tests that independently verify an implementation across component boundaries, with emphasis on executability, observability, reproducibility, assertability, and failure localization.
---

# Integration Test Builder

## Purpose

Create integration tests that verify whether an implementation satisfies its requirements and acceptance criteria.

The tests must provide independent executable evidence of correctness rather than merely mirroring the implementation.

## Core Principle: Verifiability

Optimize the test design for:

- **Executability** — the test can be run easily and consistently
- **Observability** — relevant outputs, side effects, state changes, and failures can be inspected
- **Reproducibility** — the same setup and inputs produce reliable results
- **Assertability** — success and failure conditions can be expressed as concrete assertions
- **Failure localization** — failures provide enough evidence to identify the broken boundary or behavior

## Source of Truth

Derive expected behavior primarily from:

1. task requirements
2. acceptance criteria
3. documented invariants and constraints
4. externally observable interfaces

Inspect implementation code to understand integration points and test setup, but do not derive expected behavior from the implementation itself.

Do not create tests that merely encode the current implementation.

## Workflow

### 1. Understand the contract

Identify:

- required behaviors
- acceptance criteria
- invariants
- component boundaries
- externally visible side effects
- important failure behavior

### 2. Inspect the repository

Inspect:

- relevant production code
- existing unit and integration tests
- test infrastructure
- fixtures and helpers
- runtime dependencies
- persistence boundaries
- external service boundaries

Reuse existing conventions where appropriate.

### 3. Identify integration risks

Prioritize cases where correctness depends on multiple components working together.

Examples:

- API → service → persistence
- parser → transformation → output
- producer → queue → consumer
- command → filesystem → observable result
- request → validation → domain logic → response
- configuration → runtime wiring

### 4. Design verification scenarios

Cover the smallest useful set of scenarios that gives strong evidence for the requirements.

Consider:

- primary success path
- important boundary conditions
- meaningful failure paths
- persistence and side effects
- configuration or wiring errors
- regressions implied by the task
- interactions between changed components

Avoid duplicating unit-test coverage without additional integration value.

### 5. Improve testability when necessary

If a requirement cannot be reliably verified because the system lacks observability, executability, or deterministic setup, make the smallest test-supporting improvement necessary.

Prefer:

- deterministic fixtures
- explicit test configuration
- inspectable outputs
- stable test entry points
- controlled clocks, randomness, or external dependencies

Do not introduce production complexity solely for test convenience unless necessary.

### 6. Execute the tests

Run the new integration tests and relevant existing tests.

Confirm that failures provide useful diagnostic evidence.

## Test Design Rules

Tests should:

- verify observable behavior across real component boundaries
- use real implementations when practical
- isolate only genuinely external or uncontrollable systems
- avoid excessive mocking
- keep setup deterministic
- clean up created state
- produce actionable failure messages

Do not:

- infer expected output from production implementation
- weaken assertions to match current behavior
- replace meaningful integration boundaries with mocks
- create one giant end-to-end test when smaller integration tests localize failures better
- modify unrelated production behavior

## Completion Report

Report:

- integration tests added or changed
- requirements and acceptance criteria covered
- integration boundaries exercised
- test commands executed
- results
- remaining unverified requirements
- observability or execution limitations discovered

## Output Expectation

The repository should end in a state where the relevant requirements can be independently verified through executable integration tests.

