from __future__ import annotations

import argparse
from decimal import Decimal
from typing import List

from backend.db import SessionLocal
from backend import schemas
from backend.main import _create_journal, _serialize_journal


def _print_journal(journal: schemas.JournalEntryOut) -> None:
    data = journal.model_dump()
    postings: List[dict] = data.pop("postings", [])
    print("Journal:")
    for key, value in data.items():
        print(f"  {key}: {value}")
    if postings:
        print("  postings:")
        for posting in postings:
            print("    -", posting)


def cmd_reallocate(args: argparse.Namespace) -> None:
    amount = Decimal(str(args.amount))
    postings = [
        schemas.JournalPostingIn(allocation_id=args.from_allocation_id, amount=float(-amount), currency=args.currency),
        schemas.JournalPostingIn(allocation_id=args.to_allocation_id, amount=float(amount), currency=args.currency),
    ]
    with SessionLocal() as db:
        journal = _create_journal(
            db,
            kind="REALLOC",
            note=args.note,
            created_by=args.actor,
            postings=postings,
        )
        _print_journal(_serialize_journal(journal))


def cmd_adjust(args: argparse.Namespace) -> None:
    postings = []
    for amount in args.amount:
        postings.append(
            schemas.JournalPostingIn(
                allocation_id=None,
                budget_id=args.budget_id,
                item_project_id=args.item_project_id,
                category_id=args.category_id,
                amount=float(amount),
                currency=args.currency,
            )
        )
    with SessionLocal() as db:
        journal = _create_journal(
            db,
            kind="ADJUST",
            note=args.note,
            created_by=args.actor,
            postings=postings,
        )
        _print_journal(_serialize_journal(journal))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Journal utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    realloc = sub.add_parser("realloc", help="Reallocate amount between allocations")
    realloc.add_argument("from_allocation_id", type=int)
    realloc.add_argument("to_allocation_id", type=int)
    realloc.add_argument("amount", type=float)
    realloc.add_argument("--currency", default="USD")
    realloc.add_argument("--note", default=None)
    realloc.add_argument("--actor", default="cli")
    realloc.set_defaults(func=cmd_reallocate)

    adjust = sub.add_parser("adjust", help="Post adjustment postings against a leaf category")
    adjust.add_argument("budget_id", type=int)
    adjust.add_argument("item_project_id", type=int)
    adjust.add_argument("category_id", type=int)
    adjust.add_argument("amount", type=float, nargs='+', help="One or more signed amounts that must net to zero")
    adjust.add_argument("--currency", default="USD")
    adjust.add_argument("--note", default=None)
    adjust.add_argument("--actor", default="cli")
    adjust.set_defaults(func=cmd_adjust)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
