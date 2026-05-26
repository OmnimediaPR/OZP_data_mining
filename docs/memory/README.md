# Paměť asistenta (vendorovaný snímek)

Tato složka je **kopie perzistentní paměti**, kterou si o projektu vede AI asistent (Claude Code). Slouží k tomu, aby byl kontext o projektu (architektura, konvence, číselníky, rozhodnutí) **viditelný v repu a verzovaný**, ne jen v lokálním úložišti asistenta.

- **Zdroj pravdy** je lokální úložiště asistenta (`~/.claude/projects/.../memory/`); tahle složka je jeho snímek k datu commitu a může se časem rozcházet.
- `MEMORY.md` je index (jeden řádek na poznámku); ostatní soubory jsou jednotlivé poznámky s frontmatter (`type: user | feedback | project | reference`).
- Pokud chceš snímek aktualizovat, požádej asistenta, ať paměť znovu vendoruje.
