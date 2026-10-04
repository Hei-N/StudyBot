#!/usr/bin/env python3
"""Find stored assistant replies containing leaked model reasoning (Stage 6.3).

Default: a read-only dry run. Prints chat ids, message ids and counts —
never message content — and changes nothing:

    python3 scripts/audit_reasoning_contamination.py            # default database
    python3 scripts/audit_reasoning_contamination.py --json
    python3 scripts/audit_reasoning_contamination.py --db PATH

Repair (only with the database owner's explicit approval, with
`studybot-server` stopped): backs the database up first, then rewrites only
confidently-identified replies to their answer text. Ambiguous replies are
never touched.

    python3 scripts/audit_reasoning_contamination.py --apply --backup-dir DIR --yes

Undo a repair (restores exactly the rows it changed, from its backup):

    python3 scripts/audit_reasoning_contamination.py --rollback DIR/<name>.manifest.json --yes

Repairing is optional: StudyBot already keeps confidently-identified
reasoning in old replies out of new model requests without modifying them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from studybot.config.settings import Settings
from studybot.storage.reasoning_audit import RepairManifest, audit_database, repair_database, rollback_repair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, help="database path (default: the configured StudyBot database)")
    parser.add_argument("--json", action="store_true", help="print the dry-run report as JSON")
    parser.add_argument("--apply", action="store_true", help="repair contaminated replies (needs --backup-dir, --yes)")
    parser.add_argument("--backup-dir", type=Path, help="where --apply writes its backup and manifest")
    parser.add_argument("--rollback", type=Path, metavar="MANIFEST", help="undo a repair (needs --yes)")
    parser.add_argument("--yes", action="store_true", help="confirm a modifying operation")
    args = parser.parse_args(argv)

    if args.rollback is not None:
        if not args.yes:
            print("Refusing to roll back without --yes.", file=sys.stderr)
            return 2
        restored = rollback_repair(RepairManifest.read(args.rollback))
        print(f"Restored {restored} message(s) from backup.")
        return 0

    db_path = args.db if args.db is not None else Settings.from_env().database_path
    report = audit_database(db_path)

    if args.json:
        print(json.dumps({"database": str(db_path), **report.to_dict()}, indent=2))
    else:
        print(f"Database: {db_path}")
        print(f"Assistant messages scanned: {report.assistant_messages_scanned}")
        print(f"Contaminated (repairable): {report.contaminated_count}")
        print(f"Ambiguous (left untouched): {report.ambiguous_count}")
        for chat in report.chats:
            print(
                f"  chat {chat.chat_id}: contaminated={chat.contaminated_message_ids} "
                f"ambiguous={chat.ambiguous_message_ids} removable_chars={chat.removable_chars}"
            )

    if not args.apply:
        if report.contaminated_count and not args.json:
            print("Dry run only — nothing was changed.", file=sys.stderr)
        return 0

    if args.backup_dir is None or not args.yes:
        print("Refusing to repair without both --backup-dir and --yes.", file=sys.stderr)
        return 2
    manifest = repair_database(db_path, args.backup_dir)
    print(f"Repaired {len(manifest.repaired_message_ids)} message(s). Backup: {manifest.backup}")
    print(f"Undo with: --rollback {Path(manifest.backup).with_suffix('.manifest.json')} --yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
