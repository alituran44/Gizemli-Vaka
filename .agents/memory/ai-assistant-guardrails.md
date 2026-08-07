---
name: Case-play AI assistant guardrails
description: How the in-game "Dedektif Asistanı" is prevented from leaking the case solution.
---

# Case-play AI assistant (Dedektif Asistanı)

An in-game AI mentor helps players examine evidence / ask questions / organize hints
but MUST NOT reveal or hint at the culprit or solution.

## Two-layer spoiler protection (both required)
1. **Prompt-level**: system prompt lists the case context but *deliberately excludes*
   the solution fields, plus hard "never reveal culprit/solution" rules.
2. **Deterministic post-filter** (the real safety net — never trust the prompt alone):
   after the model responds, if the reply contains any culprit/explanation keyword or
   the culprit suspect's name (keywords ≥4 chars, case-insensitive substring), the reply
   is *replaced* with a safe guidance-only fallback.

**Why:** an LLM given full case context can still name the culprit despite instructions;
a hard requirement needs a code-level guard, not just prompting.

## What context is safe to feed vs. never feed
- Feed: case title/description, evidence display names + categories + truncated stripped
  text (HTML/htm/txt only, ~600 chars each, ~6000 cap), suspect *names*, and only the
  player's already-unlocked / time-released hint texts.
- NEVER feed: `Case.culprit_keywords`, `Case.explanation_keywords`, `Suspect.is_culprit`,
  or hint reveal answers. These are exactly the fields the post-filter screens against.

## Auth model (intentional consistency, not a bug)
Case-play endpoints (`play_case`, `interrogate_suspect`, assistant) gate on **login only**
(`'user_id' in session`), not purchase/ownership. The assistant exposes nothing beyond
what `play_case` already renders, so it matches that pattern on purpose. A code review may
flag this as IDOR — changing it is an app-wide access-model change, out of scope for a
single endpoint.

**How to apply:** when adding any AI feature over case data, reuse this exact split
(safe context + deterministic keyword post-filter) and mirror the existing login-only gate.
