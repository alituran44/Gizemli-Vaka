---
name: Detective case content conventions
description: Non-obvious design rules for the static/uploads/* case file sets, so consistency passes don't "fix" intentional content.
---

# Detective case file-set conventions

Cases live as folders of standalone HTML evidence files under `static/uploads/<case-slug>/`.
When scanning a case for contradictions/gaps, distinguish *real errors* from *intentional design*:

- **Planted clues / red herrings / open mystery questions are intentional.** Never "resolve" them.
- **Two-layer cases exist.** `colun-muhurlu-haritasi` ("Çölün Mühürlü Haritası") has a MODERN 2026
  illegal-excavation/smuggling layer (detective "Orhan Demir", ~11 files) AND a HISTORICAL 1872
  disappearance layer (detective "Emirhan Yılmaz, Başkomiser", 3 files: Telefon_Kayitlari,
  Kamil_Aga_Profil, Supheli_Mahmut_Efendi). The two different detective names are deliberate layer
  separation — not an inconsistency. The 1872 death date (11.03.1872) is intentional.
- **Personal character details** (e.g. a suspect's birthplace/residence being a different city) are
  legitimate even when they differ from the case's jurisdiction city.

**Why:** explorer subagents repeatedly misread these as contradictions; "fixing" them would destroy the puzzle.

**How to apply (resolving a *genuine* contradiction):** pick the canonical value by authority first
(the `Dedektif_Ozet_Raporu.html` master summary wins), then majority, then hard-evidence files;
make minority files match. Prefer values that keep the timeline causally coherent (e.g. discovery
date must precede the crime it enables). Verify fixes with a folder-level `grep` sweep.
