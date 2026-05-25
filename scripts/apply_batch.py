#!/usr/bin/env python3
"""Aplikuje jeden batch schválených entries do data/catalog.json.

Použití:
    python3 scripts/apply_batch.py docs/discovery/batch_approvals/batch_NN_xxx.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"


def main(batch_file: str) -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    batch = json.loads(Path(batch_file).read_text(encoding="utf-8"))

    existing_ids = {d["id"] for d in catalog["datasets"]}
    new_entries = batch["entries"]

    duplicates = [e["id"] for e in new_entries if e["id"] in existing_ids]
    if duplicates:
        print(f"CHYBA: duplicit ID v catalog.json: {duplicates}", file=sys.stderr)
        return 1

    catalog["datasets"].extend(new_entries)
    catalog["updated"] = batch["approved_at"]

    CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"→ {len(new_entries)} entries přidáno do data/catalog.json")
    print(f"  Celkem v katalogu: {len(catalog['datasets'])} datasetů")
    for e in new_entries:
        print(f"  + {e['id']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Použití: python3 scripts/apply_batch.py <batch_file.json>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
