---
name: Case evidence personalization
description: How/why player-name personalization of case evidence HTML works, and the invariants any change must keep.
---

# Player-name personalization of case evidence

Evidence HTML is personalized **at serve time** (not stored): the case-file route
reads the HTML and swaps the *investigating-detective identity* for the logged-in
player's display name, so each player feels like the detective on the case. This
is a deliberate UX requirement from the owner ("kullanıcı kendini dedektif gibi
hissetsin").

**Why serve-time, not edited files:** the same player name must appear for every
different player, and the source files stay canonical/editable.

## Invariants any change to the personalizer MUST keep
- **Only the investigator identity is swapped.** Suspects, witnesses, and forensic
  experts (Dr./Prof./Müh.) are NOT the player — leave them. (The player is the
  detective, not the coroner; that's why forensic-name replacement was removed.)
- **Annotation labels are not names.** "Dedektif Notu", "Başkomiser Notu",
  "Soruşturmacı Değerlendirmesi", unit names ("... Şubesi/Müdürlüğü") must survive
  — only the *name* after a rank is swapped. Title-based replacement uses a
  negative lookahead against an annotation/unit word list to achieve this.
- **Historical/period figures must be preserved.** colun's 1872 layer detective
  "Emirhan Yılmaz" is protected (sentinel-token round-trip) — a modern player
  cannot be a detective in 1872. Modern lead "Orhan Demir" IS swapped. (See
  case-content-conventions.md for the two-layer design.)
- **Bare untitled lead names** need a per-case allow-list (e.g. "Ali Turan",
  "Orhan Demir") because the rank-based regex won't catch them.
- Player name is inserted via **callable** re.sub replacements (literal-safe) and
  the "Dedektif" rank prefix is skipped when the name itself starts with
  "Dedektif" (avoids "Dedektif Dedektif" for the anonymous fallback).

**How to apply:** after editing the personalizer, curl real files across all 6
cases and assert: officer fields show the name, annotation labels intact, suspects
untouched, Emirhan Yılmaz intact, no "Dedektif Dedektif".

**Access note:** these files are also publicly reachable via `/media/` and
`/static/uploads/`, so the personalized route is not an access-control boundary;
it only needs path-traversal confinement to the uploads root.
