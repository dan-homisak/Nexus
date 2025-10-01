"""Backfill existing entry/allocations into the immutable ledger.

The script is idempotent: use the --dry-run flag to preview changes. On apply it
creates funding sources (if they are missing) and inserts transactions/events
reflecting the current entry table, along with best-effort payment schedules and
baseline FX rates.
"""
from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend import models, models_finance
from backend.sql.views import apply_views

KIND_TO_STATE = {
    "budget": ("FORECAST", "QUOTE"),
    "quote": ("FORECAST", "QUOTE"),
    "po": ("COMMITMENT", "PO"),
    "unplanned": ("ACCRUAL", "INVOICE"),
    "adjustment": ("JOURNAL", "JOURNAL"),
}

DEFAULT_CURRENCY = "USD"


def ensure_fx_rate(session: Session, currency: str, txn_date: dt.date) -> models_finance.FxRate:
    currency = currency.upper()
    try:
        return models_finance.FxRate.lookup(session, txn_date, currency, allow_stale=True)
    except LookupError:
        rate = models_finance.FxRate(
            quote_currency=currency,
            valid_from=txn_date,
            rate=Decimal("1.0"),
        )
        session.add(rate)
        session.flush()
        return rate


def compute_amount_usd(rate: models_finance.FxRate, amount: Decimal) -> Decimal:
    return (Decimal(amount) * Decimal(rate.rate)).quantize(Decimal("0.000001"))


def backfill_transactions(session: Session, *, dry_run: bool = False) -> dict[str, int]:
    summary: dict[str, int] = defaultdict(int)

    legacy_to_fs = {}
    for fs in session.execute(select(models_finance.FundingSource)).scalars():
        if fs.legacy_portfolio_id:
            legacy_to_fs[fs.legacy_portfolio_id] = fs

    if not legacy_to_fs:
        for portfolio in session.execute(select(models.Portfolio)).scalars():
            fs = models_finance.FundingSource(
                name=portfolio.name,
                type="COST_CENTER",
                is_temporary=False,
                legacy_portfolio_id=portfolio.id,
                legacy_fiscal_year=portfolio.fiscal_year,
                legacy_owner=portfolio.owner,
            )
            session.add(fs)
            session.flush()
            legacy_to_fs[portfolio.id] = fs
            summary["funding_sources_created"] += 1

    for entry in session.execute(select(models.Entry)).scalars():
        state, source_type = KIND_TO_STATE.get(entry.kind, ("ACCRUAL", "JOURNAL"))
        funding_source = legacy_to_fs.get(entry.portfolio_id)
        if not funding_source:
            funding_source = models_finance.FundingSource.ensure(
                session,
                name=f"Legacy-{entry.portfolio_id}",
                type="COST_CENTER",
                is_temporary=True,
                legacy_portfolio_id=entry.portfolio_id,
            )
        txn_date = entry.date or dt.date.today()
        rate = ensure_fx_rate(session, DEFAULT_CURRENCY, txn_date)
        usd_amount = compute_amount_usd(rate, Decimal(entry.amount))
        existing = session.execute(
            select(models_finance.Transaction).where(
                models_finance.Transaction.source_type == source_type,
                models_finance.Transaction.source_id == str(entry.id),
            )
        ).scalar_one_or_none()
        if existing:
            summary["transactions_skipped"] += 1
            continue
        txn = models_finance.Transaction(
            funding_source=funding_source,
            project_id=entry.project_id,
            category_id=entry.category_id,
            vendor_id=entry.vendor_id,
            state=state,
            source_type=source_type,
            source_id=str(entry.id),
            amount_txn=Decimal(entry.amount),
            currency=DEFAULT_CURRENCY,
            fx_rate_to_usd=rate.rate,
            amount_usd=usd_amount,
            txn_date=txn_date,
            memo=entry.description,
            tags=[tag.name for tag in session.execute(
                select(models.Tag).join(models.EntryTag, models.EntryTag.tag_id == models.Tag.id).where(
                    models.EntryTag.entry_id == entry.id
                )
            ).scalars()],
        )
        session.add(txn)
        summary["transactions_created"] += 1

        event = models_finance.Event(
            entity_type="transaction",
            entity_id=txn.id,
            event_type="backfill_created",
            at=dt.datetime.now(dt.timezone.utc),
            by="system",
            payload_json={"entry_id": entry.id, "kind": entry.kind},
        )
        session.add(event)
        summary["events_created"] += 1

    if dry_run:
        session.rollback()
    else:
        session.commit()
        apply_views(session.bind)
    return summary


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill immutable transactions")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist changes")
    args = parser.parse_args(list(argv) if argv is not None else None)

    with SessionLocal() as session:
        summary = backfill_transactions(session, dry_run=args.dry_run)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":  # pragma: no cover
    main()
