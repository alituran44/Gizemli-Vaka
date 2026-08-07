---
name: Success file editing
description: How the per-case "başarı dosyası" success report files are stored, served, and safely edited.
---

# Success ("Başarı Dosyası") report files

Each case has a success report HTML served after the player solves it. The DB column `case.success_file` holds just the filename (e.g. `Basar_Mesaj.html` or `Basari_Dosyasi.html`); the file lives at `static/uploads/<case.id>/<success_file>`. **`case.id` IS the folder name** (e.g. `colun-muhurlu-haritasi`, `104.2 Çanakkale Paradoksu`). Served via the `/vaka/<case_id>/dosya/<filename>` route, which runs `personalize_case_html`.

## Editing gotcha: line endings vary per file
These legacy upload files do NOT have uniform EOLs — some are CRLF (`\r\n`, e.g. Çanakkale `Basar_Mesaj.html`), some are LF-only (e.g. Gölge `Basar_Mesaj.html`).

**Why:** The `edit` tool matches verbatim including `\r`. A copy of a line that looks identical will fail with "old_string did not appear verbatim" when the file is CRLF but your old_string uses LF.

**How to apply:** Inspect with `sed -n 'N,Mp' file | cat -A` (look for `^M$`). To insert/replace, use a small Python script that opens with `newline=''` (preserves existing EOLs), detects `nl = '\r\n' if '\r\n' in content else '\n'`, and builds replacement strings with that `nl`. This preserves each file's native endings — do NOT normalize. A file being uniformly LF is fine; only *mixed* endings are a real problem.

## Content/safety invariants when adding sections
- `personalize_case_html` only swaps the investigator/detective identity (rank-prefixed names like "Başkomiser/Dedektif X"). Civilian suspect names in content are safe — but never write a suspect's name with a police-rank prefix, or it will be swapped.
- Sign-offs: use `<strong>Başkomiser</strong>` with NO name after it (the personalize route would otherwise inject the player name there).
- NEVER alter the `<!-- SUCLU: ... -->` / `<!-- ACIKLAMA: ... -->` comments — they must stay byte-equal to the case's `culprit_keywords` (in `initial_data.json` / DB) or the game's accepted answer breaks.
- `static/uploads/**` is gitignored, so `git diff` won't show changes to these files — verify by curling `/vaka/<id>/dosya/<file>` (expect 200 + your new content, no name mangling).
