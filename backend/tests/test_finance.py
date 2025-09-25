from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import Base
from backend import models, models_finance  # noqa: F401 - ensure legacy tables load


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_payment_schedule_default_generates_due_date():
    session = build_session()
    po = models_finance.PurchaseOrder(
        funding_source=models_finance.FundingSource(name="FS", type="COST_CENTER"),
        po_number="PO-1",
        currency="USD",
    )
    session.add(po)
    session.commit()
    schedules = models_finance.PaymentSchedule.generate_default(session=session, purchase_order=po, net_days=60)
    assert len(schedules) == 1
    schedule = schedules[0]
    assert schedule.net_days == 60
    session.close()


def test_transaction_reversal_pair_creates_events():
    session = build_session()
    fs = models_finance.FundingSource(name="FS", type="COST_CENTER")
    session.add(fs)
    session.flush()
    txn = models_finance.Transaction(
        funding_source=fs,
        state="ACCRUAL",
        source_type="INVOICE",
        amount_txn=Decimal("100"),
        currency="USD",
        fx_rate_to_usd=Decimal("1.0"),
        amount_usd=Decimal("100"),
        txn_date=dt.date.today(),
    )
    session.add(txn)
    session.flush()
    reverse, replacement = models_finance.Transaction.create_reversal_pair(
        session,
        txn,
        reason="correction",
        by="tester",
    )
    assert reverse.amount_txn == Decimal("-100")
    assert replacement.reverses_transaction_id is None
    session.close()


def test_fx_lookup_respects_bounds():
    session = build_session()
    rate = models_finance.FxRate(
        quote_currency="EUR",
        valid_from=dt.date(2024, 1, 1),
        rate=Decimal("1.2"),
    )
    session.add(rate)
    session.flush()
    found = models_finance.FxRate.lookup(session, dt.date(2024, 1, 10), "EUR", allow_stale=True)
    assert found.rate == Decimal("1.2")
    session.close()
