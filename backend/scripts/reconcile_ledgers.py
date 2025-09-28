"""Utility command to recompute category rollups and budget caches.

The migration triggers keep values up to date in normal operation, but this
command lets operators reconcile drift (cron/nightly) and assists in tests.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Dict, Iterable, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend import models, models_finance  # noqa: F401 - ensure metadata is loaded


def _walk_paths(
    node: models.Category,
    children: Dict[int, List[models.Category]],
    ancestors_ids: List[int],
    ancestors_names: List[str],
) -> Iterable[models.Category]:
    path_ids = ancestors_ids + [node.id]
    path_names = ancestors_names + [node.name]
    node.path_ids = json.dumps(path_ids)
    node.path_names = json.dumps(path_names)
    node.path_depth = len(path_ids) - 1

    for child in children.get(node.id, []):
        yield from _walk_paths(child, children, path_ids, path_names)
    yield node


def _compute_totals(
    node: models.Category,
    children: Dict[int, List[models.Category]],
) -> Decimal:
    kids = children.get(node.id, [])
    node.is_leaf = len(kids) == 0
    if node.is_leaf:
        amount = Decimal(str(node.amount_leaf or 0))
        node.rollup_amount = amount
        return amount

    # parent node; ensure amount stored only on leaves
    node.amount_leaf = None
    subtotal = Decimal("0")
    for child in kids:
        subtotal += _compute_totals(child, children)
    node.rollup_amount = subtotal
    return subtotal


def reconcile_ledgers(session: Session) -> dict:
    categories = session.execute(select(models.Category)).scalars().all()
    by_budget: Dict[int, List[models.Category]] = defaultdict(list)
    children: Dict[int, List[models.Category]] = defaultdict(list)
    for cat in categories:
        by_budget[cat.budget_id].append(cat)
        if cat.parent_id:
            children[cat.parent_id].append(cat)

    updated_budgets: Dict[int, Decimal] = {}

    for budget_id, cats in by_budget.items():
        roots = [c for c in cats if c.parent_id is None]
        # Rebuild ordering for deterministic traversal
        for root in roots:
            for node in _walk_paths(root, children, [], []):
                # generator already mutates node paths
                pass
        for root in roots:
            _compute_totals(root, children)

        total = sum(
            Decimal(str(cat.amount_leaf or 0))
            for cat in cats
            if cat.is_leaf
        )
        budget = session.get(models_finance.FundingSource, budget_id)
        if budget:
            if budget.is_cost_center:
                budget.budget_amount_cache = None
            else:
                budget.budget_amount_cache = total
            budget.updated_at = None  # trigger default via SQLAlchemy on flush
        updated_budgets[budget_id] = total

    session.commit()
    return {
        "budgets_reconciled": len(updated_budgets),
        "totals": {k: str(v) for k, v in updated_budgets.items()},
    }


def main() -> None:
    with SessionLocal() as session:
        stats = reconcile_ledgers(session)
        print(
            json.dumps(
                {
                    "ok": True,
                    **stats,
                },
                indent=2,
            )
        )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
