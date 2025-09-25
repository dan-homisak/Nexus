from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import Base
from backend import models, models_finance  # noqa: F401 - ensure legacy tables load
from backend.routes_finance import (
    apply_deliverable_template,
    create_fx_rate,
    get_budget_commit_actual,
    payment_schedule_generate,
    run_report_adhoc,
    update_fx_rate,
    update_milestone,
    update_payment_schedule,
)
from backend.schemas_finance import (
    DeliverableTemplateApplyRequest,
    FxRateIn,
    FxRateUpdateIn,
    MilestoneUpdateIn,
    PaymentScheduleGenerateV2Request,
    PaymentScheduleUpdateIn,
    ReportRunIn,
)


def make_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_payment_schedule_default_generates_due_date():
    SessionLocal = make_session_factory()
    session = SessionLocal()
    try:
        po = models_finance.PurchaseOrder(
            funding_source=models_finance.FundingSource(name="FS", type="COST_CENTER"),
            po_number="PO-1",
            currency="USD",
        )
        session.add(po)
        session.commit()
        schedules = models_finance.PaymentSchedule.generate_default(
            session=session, purchase_order=po, net_days=60
        )
        assert len(schedules) == 1
        schedule = schedules[0]
        assert schedule.net_days == 60
    finally:
        session.close()


def test_transaction_reversal_pair_creates_events():
    SessionLocal = make_session_factory()
    session = SessionLocal()
    try:
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
    finally:
        session.close()


def test_fx_lookup_respects_bounds():
    SessionLocal = make_session_factory()
    session = SessionLocal()
    try:
        rate = models_finance.FxRate(
            quote_currency="EUR",
            valid_from=dt.date(2024, 1, 1),
            rate=Decimal("1.2"),
        )
        session.add(rate)
        session.flush()
        found = models_finance.FxRate.lookup(
            session, dt.date(2024, 1, 10), "EUR", allow_stale=True
        )
        assert found.rate == Decimal("1.2")
    finally:
        session.close()


def test_analytics_budget_endpoint():
    SessionLocal = make_session_factory()
    with SessionLocal() as session:
        fs = models_finance.FundingSource(name="FS", type="COST_CENTER")
        session.add(fs)
        session.flush()
        txn = models_finance.Transaction(
            funding_source_id=fs.id,
            state="FORECAST",
            source_type="PO",
            amount_txn=Decimal("100"),
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            amount_usd=Decimal("100"),
            txn_date=dt.date.today(),
        )
        session.add(txn)
        session.commit()

    with SessionLocal() as session:
        data = get_budget_commit_actual(db=session)
    assert data and "budget_usd" in data[0]


def test_payment_schedule_generate_creates_default():
    SessionLocal = make_session_factory()
    with SessionLocal() as session:
        fs = models_finance.FundingSource(name="FS", type="COST_CENTER")
        session.add(fs)
        session.flush()
        po = models_finance.PurchaseOrder(
            funding_source=fs,
            po_number="PO-100",
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            total_amount=Decimal("100"),
            amount_usd=Decimal("100"),
        )
        session.add(po)
        session.commit()
        po_id = po.id

    with SessionLocal() as session:
        result = payment_schedule_generate(
            PaymentScheduleGenerateV2Request(po_id=po_id, rule="NET_N", net_days=60),
            db=session,
        )
        assert len(result) == 1

    with SessionLocal() as session:
        event = session.execute(
            select(models_finance.Event).where(
                models_finance.Event.entity_type == "payment_schedule"
            )
        ).scalar_one_or_none()
        assert event is not None


def test_payment_schedule_update_rejects_paid_changes():
    SessionLocal = make_session_factory()
    with SessionLocal() as session:
        schedule = models_finance.PaymentSchedule(
            percent=Decimal("1"),
            amount=Decimal("50"),
            due_date_rule="NET_N",
            status="PAID",
            paid_transaction_id="txn",
        )
        session.add(schedule)
        session.commit()
        schedule_id = schedule.id

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            update_payment_schedule(
                schedule_id,
                PaymentScheduleUpdateIn(amount=Decimal("20")),
                db=session,
            )
        assert exc.value.status_code == 400


def test_deliverable_template_apply_and_milestone_update():
    SessionLocal = make_session_factory()
    with SessionLocal() as session:
        fs = models_finance.FundingSource(name="FS", type="COST_CENTER")
        checkpoint = models_finance.CheckpointType(code="ship", name="Ship")
        session.add_all([fs, checkpoint])
        session.flush()
        po = models_finance.PurchaseOrder(
            funding_source=fs,
            po_number="PO-200",
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            total_amount=Decimal("10"),
            amount_usd=Decimal("10"),
        )
        session.add(po)
        session.flush()
        line = models_finance.POLine(
            purchase_order=po,
            description="Widget",
            quantity=Decimal("10"),
            amount=Decimal("10"),
        )
        session.add(line)
        session.commit()
        po_id = po.id
        line_id = line.id
        checkpoint_id = checkpoint.id

    with SessionLocal() as session:
        lots = apply_deliverable_template(
            DeliverableTemplateApplyRequest(
                purchase_order_id=po_id,
                po_line_ids=[line_id],
                lot_quantities=[Decimal("5")],
                checkpoint_type_ids=[checkpoint_id],
            ),
            db=session,
        )
        assert lots and lots[0].milestones
        milestone_id = lots[0].milestones[0].id

    with SessionLocal() as session:
        updated = update_milestone(
            milestone_id,
            MilestoneUpdateIn(actual_date=dt.date.today()),
            db=session,
        )
        assert updated.actual_date == dt.date.today()


def test_fx_rate_bounds_and_override():
    SessionLocal = make_session_factory()
    with SessionLocal() as session:
        rate = create_fx_rate(
            FxRateIn(quote_currency="EUR", valid_from=dt.date(2024, 1, 1), rate=Decimal("1.1")),
            db=session,
        )
        rate_id = rate.id

    with SessionLocal() as session:
        with pytest.raises(HTTPException):
            update_fx_rate(rate_id, FxRateUpdateIn(rate=Decimal("3")), db=session)

    with SessionLocal() as session:
        updated = update_fx_rate(
            rate_id,
            FxRateUpdateIn(rate=Decimal("3"), manual_override=True),
            db=session,
        )
        assert Decimal(updated.rate) == Decimal("3")


def test_report_run_adhoc():
    SessionLocal = make_session_factory()
    with SessionLocal() as session:
        fs = models_finance.FundingSource(name="FS", type="COST_CENTER")
        session.add(fs)
        session.flush()
        txn = models_finance.Transaction(
            funding_source_id=fs.id,
            state="FORECAST",
            source_type="PO",
            amount_txn=Decimal("50"),
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            amount_usd=Decimal("50"),
            txn_date=dt.date.today(),
        )
        session.add(txn)
        session.commit()

    with SessionLocal() as session:
        result = run_report_adhoc(
            ReportRunIn(json_config={"view": "v_budget_commit_actual"}),
            db=session,
        )
        assert result.rows
