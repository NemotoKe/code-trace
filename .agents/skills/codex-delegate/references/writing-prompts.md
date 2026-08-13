# Writing a delegation prompt

Every rule here comes from something that actually went wrong or right on this
repository. The measured cost of getting this wrong: two corrective passes
consumed **34% of all input tokens and 29% of all output tokens** across nine
Codex sessions, and produced no new capability. Both were caused by the prompt,
not by the worker.

## The shape

```
# Task: <one line>

## Objective          desired end state in 1-3 sentences, plus what is NOT in it
## Context            repo path, the files that matter, the pattern to follow
## Requirements       R1, R2, ... each with concrete examples
## Acceptance Criteria  at most 3
## TDD                what to red-green, and where the tests go
## Constraints        allowed to change / must not change, language, deps
## Non-goals          the next units, by name
## Report             exactly what to measure and hand back
```

## Rules

### 1. Write requirements as inputs with expected outputs, not as principles

An abstract constraint is the one that gets dropped. A table of cases is the one
that survives.

| ✗ dropped | ✓ kept |
|---|---|
| "Preserve the explanatory comments that state why" | "`retVal.putIfAbsent(..., new SpringBeanContainer(f))` must not produce a method named `SpringBeanContainer`" |
| "Handle generics correctly" | `class Foo extends Base<Bar, Baz>` → extends `Base` — **not** `Bar`, **not** `Baz` |

The first pair is real: the abstract version was ignored and produced 66 phantom
methods in HAPI. The second shape has not been missed once.

Prefer an actual table:

```
| Declaration | Expected |
|---|---|
| `class Foo<T extends Comparable<T>> extends Base {` | extends `Base` — the bound is a type parameter |
| `sealed class Foo extends Base permits A, B {`      | extends `Base` — permits lists subtypes |
```

### 2. If it is data, paste it

A list defined by a specification is data. Describing it invites an incomplete
reconstruction. The 104 `java.lang` type names were pasted verbatim with "do not
shorten it, do not add to it" — clean on the first attempt.

### 3. Constrain *where*, not only *what*

"Do not re-read files that were already read" was satisfied by loading the entire
source tree into memory, which cost +63 MB of resident set that scales with the
repository. The instruction was obeyed; the prompt simply had not said where the
text was allowed to live.

Say the shape of the answer when the shape matters: *"a worker reads a file once
and returns extracted data only; source text never accumulates in the parent and
never crosses the process boundary."*

### 4. Measure expected values before asserting them

Numbers written from memory or from a throwaway script get contradicted.

- "IBase reaches depth 7" — wrong; a depth-first audit script recorded the first
  path found, not the shortest. The worker pushed back with evidence and was
  right.
- "280 subtypes" — wrong; that was how often the name appeared, not the size of
  the closure.

Either verify the number first, or label it: *"illustrative — report the actual
value."* A wrong hard number invites the worker to bend correct code to match it.

### 5. Name the files that may change, and the files that may not

```
- **Allowed to change:** codewiki/cli.py, README.md, and tests.
- **Must not change:** codewiki/query/, codewiki/store/, codewiki/index/.
```

Without this, a unit that only needed to add a CLI command rewrote the pipeline.

Include the human's uncommitted work explicitly:

```
- codewiki/index/symbols.py has uncommitted edits by the repository owner.
  Do not touch that file at all.
```

### 6. State non-goals by name

List the *next* units. "Not in this unit: extends/implements parsing, type
hierarchy, subtype closure, call edges, callers/callees, SQL analysis, entry
points, trace." Naming them is what stops a worker from helpfully starting them.

### 7. Put the verification in the prompt

What you ask to be reported is what gets measured.

```
- Peak RSS indexing HAPI is at or below the 425 MB baseline, measured with
  `/usr/bin/time -l`. Report the number.
- The supertypes table still holds exactly 4,190 rows with outcomes
  resolved 3,448 / external 501 / unresolved 241 / excluded 0.
- `grep -rn "extract_all\|parse_all"` shows no definition without a caller.
```

Each line is checkable by someone who was not there. "Make sure it is still
fast" is not.

### 8. Give the reason when a rule looks arbitrary

A worker that understands why a rule exists applies it to cases the prompt did
not list.

> The fallback is last **because the JLS puts it last**: `java.lang.*` is an
> import-on-demand, so a same-file type, an explicit import, and a same-package
> type all shadow it.

That prompt produced correct handling of three shadowing cases that were never
enumerated.

### 9. Point at the pattern to copy

> `imports` and `type_resolutions` already do exactly this end to end. Follow
> that pattern rather than inventing one: note how `candidates` is stored as
> sorted JSON, and how rows are sorted before insert so re-indexing is
> deterministic.

Cheaper than describing the convention, and it cannot drift from the code.

### 10. Cap acceptance criteria at three

Not a style preference. Measured: 14 criteria silently dropped two instructions;
6 still produced a defect affecting 22,000 records; 3 has been clean. If a unit
needs more than three, it is more than one unit.

## Corrective passes

Same rules, plus: lead with what is **already verified and must not change**, so
the fix does not undo working behavior.

```
Unit H2b is functionally correct and verified independently: <evidence>.
All three acceptance criteria pass. Do not change the schema, the writer,
the CLI output, or the resolution.

One defect, in codewiki/index/pipeline.py only.
## Defect — <one line>
<evidence: measured numbers, before and after>
### Required correction
### Verification required
```

Say plainly when the prompt caused the defect — *"the instruction was mine, and
holding the sources is one way to satisfy it"* — and keep the part that was a
genuine improvement. It prevents the worker from reverting good work along with
the bad.

## Anti-patterns

- **"Implement this feature."** Nothing to check, nothing to refuse.
- **Reporting a completion report as verification.** The report is silent about
  instructions that were dropped. Execute each criterion yourself.
- **Mixing new schema design with new logic.** Decide the schema yourself and
  paste the DDL; then the delegation is application, not design.
- **Asking for tests without stating the contract.** A loose request produces
  tests that restate the implementation and catch nothing.
