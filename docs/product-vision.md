# cURLsender Product Vision

## Consensus

Three `gpt-5.4` agents worked from complementary angles:

- UI: visual structure, component hierarchy, and mockup directions
- PM: positioning, scope, priorities, and roadmap
- UX: flows, clarity, feedback, and interaction quality

Shared conclusion:

- cURLsender should remain a fast, faithful `curl` runner, not become an API client.
- The core promise is still `paste, run, read`.
- Improvements should reduce ambiguity and increase confidence without adding heavy abstractions.
- Features such as history, collections, request builders, environments, and pretty-print-first flows stay out of scope.

## Product Thesis

`cURLsender` is the fastest trustworthy desktop utility for executing a pasted `curl` command and reading the raw response without rebuilding the request elsewhere.

### Primary audience

- Developers reproducing requests from browser DevTools, docs, Slack, tickets, or logs
- QA and support engineers validating an API call quickly
- Technical users who know `curl` but want less friction than opening a terminal

### Product principles

- Fidelity before convenience
- One-screen workflow
- Raw output remains the source of truth
- Advanced assistance stays secondary and lightweight
- The app should feel faster and calmer, never heavier

## Final Structure

The agreed product structure is a single screen with five zones:

1. Compact header with product identity, execution status, and primary action context
2. `Command` editor with line numbers and shortcut hint
3. Lightweight `Preflight` row with inferred method, host, headers, body presence, and warnings
4. Action bar with `Execute/Cancel`, `Validate`, and clear actions
5. `Execution Summary` plus raw `Output` area, supported by reading tools like wrap, auto-scroll, copy, and find

## Scope

### V1: Trust & Flow

- Lightweight preflight analysis
- Clearer execution states: `idle`, `running`, `cancelling`, `done`, `error`
- Execution summary separated from raw output
- Better parse and runtime error messaging
- Safer persistence for last command and basic UI preferences
- Output reading tools: wrap, auto-scroll, copy all, find
- More explicit cancel behavior and status feedback

### V2: Debug Assist

- Open/save snippet manually
- More preventive warnings, including Windows command length risk
- Additional keyboard ergonomics and reading preferences
- Optional inspection helpers that do not reconstruct the request
- Optional secret detection/redaction guidance

## Non-goals

- Request builder
- Request history or collections
- Environments, auth vaults, or profiles
- Pretty-print-first experience
- Multi-tab workspace model
- Turning the app into a Postman/Bruno alternative

## Chosen Mockup Set

The consensus selected five differentiated directions:

1. `Baseline Refined`
2. `Split Operator`
3. `Reader First`
4. `Console Signal`
5. `Calm Lab`

### Recommended lead direction

`Console Signal` is the recommended primary direction because it best balances:

- execution confidence and live system feedback
- clearer hierarchy for command, summary, and raw output
- a natural home for dark/light theme switching in the header
- a clean migration path to a rounded Qt Widgets shell without changing the product thesis

`Baseline Refined` is the safest fallback direction.

## Mockup Notes

The interactive gallery lives at:

- [docs/mockups/index.html](/C:/Users/Guilherme/Documents/Claude/cURLsender/docs/mockups/index.html)

Each mockup preserves the same product structure while testing different emphasis:

- `Baseline Refined`: safest evolution of the current UI
- `Split Operator`: balanced command/output split for active debugging
- `Reader First`: output-centered reading for longer responses
- `Console Signal`: instrumentation-heavy live execution feel
- `Calm Lab`: precise, minimal, calm interface with strong technical hierarchy
