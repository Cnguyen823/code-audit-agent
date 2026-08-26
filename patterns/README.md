# Pattern Library

Hand-curated anti-pattern entries the Pattern Checker retrieves against.
Written by hand, not generated — the library's value is in what a human
judged actually matters, not in coverage for its own sake.

This directory is intentionally empty except this README. Patterns get
added by hand as they're curated.

## Entry Format

One file per pattern: `patterns/<slug>.md`

```markdown
# <Pattern Name>

## Symptoms
What this looks like in code — the signals to retrieve on.

## Why It's a Problem
The actual risk this causes, not just "it's ugly."

## Example (bad)
A short code snippet showing the pattern.

## Fix
What the corrected version looks like, and why it's better.

## Confidence Signals
Keywords or structural cues that indicate a high- vs. low-confidence match —
what the Pattern Checker's verification step should look for before trusting
a retrieval hit.
```
