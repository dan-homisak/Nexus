from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import models, models_finance, schemas
from backend.main import _create_journal, _serialize_journal, journal_adjust, journal_reallocate, update_entry
from backend.migrations.versions.dde21381ed8c_pr2_journals_immutability import TRIGGERS


def make_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    conn = engine.connect()
    for name, sql in TRIGGERS:
        conn.exec_driver_sql(sql)
    conn.close()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db_session():
    SessionLocal = make_session_factory()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()



def _seed_ledger(session):
    fs = models_finance.FundingSource(name="Budget-A", type="COST_CENTER", is_cost_center=False)
    session.add(fs)
    session.flush()
    project = models.Project(name="Project-A", portfolio_id=1, budget_id=fs.id)
    session.add(project)
    session.flush()
    category = models.Category(
        name="Leaf",
        budget_id=fs.id,
        item_project_id=project.id,
        is_leaf=True,
    )
    session.add(category)
    session.flush()
    entry = models.Entry(
        kind="expense",
        amount=100.0,
        portfolio_id=1,
        project_id=project.id,
        item_project_id=project.id,
        category_id=category.id,
    )
    session.add(entry)
    session.flush()
    allocation = models.Allocation(
        entry_id=entry.id,
        item_project_id=project.id,
        category_id=category.id,
        budget_id=fs.id,
        amount=Decimal("100"),
        currency="USD",
    )
    session.add(allocation)
    session.commit()
    return fs, project, category, entry, allocation


def test_entries_append_only_trigger(db_session):
    _, _, _, entry, _ = _seed_ledger(db_session)
    with pytest.raises(Exception):
        db_session.execute(text("UPDATE entries SET amount = amount + 1 WHERE id = :id"), {"id": entry.id})
        db_session.commit()
    db_session.rollback()
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM entries WHERE id = :id"), {"id": entry.id})
        db_session.commit()
    db_session.rollback()


def test_allocations_append_only_trigger(db_session):
    _, _, _, entry, alloc = _seed_ledger(db_session)
    with pytest.raises(Exception):
        db_session.execute(text("UPDATE allocations SET amount = amount + 1 WHERE id = :id"), {"id": alloc.id})
        db_session.commit()
    db_session.rollback()
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM allocations WHERE id = :id"), {"id": alloc.id})
        db_session.commit()
    db_session.rollback()


def test_journal_balance_trigger(db_session):
    _, _, _, _, alloc = _seed_ledger(db_session)
    entry = models.JournalEntry(kind="REALLOC")
    db_session.add(entry)
    db_session.flush()
    db_session.add(models.JournalPosting(journal_id=entry.id, allocation_id=alloc.id, amount=Decimal("10"), currency="USD"))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_create_journal_entry_balanced(db_session):
    fs, project, category, _, alloc = _seed_ledger(db_session)
    payload = schemas.JournalEntryIn(
        kind="REALLOC",
        postings=[
            schemas.JournalPostingIn(allocation_id=alloc.id, amount=-50.0),
            schemas.JournalPostingIn(budget_id=fs.id, item_project_id=project.id, category_id=category.id, amount=50.0),
        ],
    )
    entry = _create_journal(db_session, kind=payload.kind, note=None, created_by=None, postings=payload.postings)
    serialized = _serialize_journal(entry)
    assert serialized.balanced is True
    assert abs(serialized.net_amount) < 1e-6


def test_update_entry_api_rejected(db_session):
    _, _, _, entry, _ = _seed_ledger(db_session)
    entry_in = schemas.EntryIn(kind="expense", amount=100.0, portfolio_id=1)
    with pytest.raises(HTTPException) as exc:
        update_entry(entry.id, entry_in, db_session)
    assert exc.value.status_code == 409


def test_journal_reallocate_helper(db_session):
    _, _, _, _, alloc1 = _seed_ledger(db_session)
    alloc2 = models.Allocation(
        entry_id=alloc1.entry_id,
        item_project_id=alloc1.item_project_id,
        category_id=alloc1.category_id,
        budget_id=alloc1.budget_id,
        amount=Decimal("20"),
        currency="USD",
    )
    db_session.add(alloc2)
    db_session.commit()
    payload = schemas.JournalReallocateIn(
        from_allocation_id=alloc1.id,
        to_allocation_id=alloc2.id,
        amount=10.0,
    )
    result = journal_reallocate(payload, db_session)
    assert result.balanced is True
    db_session.refresh(alloc1)
    db_session.refresh(alloc2)
    assert pytest.approx(float(alloc1.effective_amount), rel=1e-6) == 90.0
    assert pytest.approx(float(alloc2.effective_amount), rel=1e-6) == 30.0


def test_journal_adjust_requires_balance(db_session):
    fs, project, category, _, _ = _seed_ledger(db_session)
    payload = schemas.JournalAdjustIn(
        postings=[
            schemas.JournalPostingIn(budget_id=fs.id, item_project_id=project.id, category_id=category.id, amount=25.0),
            schemas.JournalPostingIn(budget_id=fs.id, item_project_id=project.id, category_id=category.id, amount=-25.0),
        ]
    )
    result = journal_adjust(payload, db_session)
    assert result.balanced is True


def test_journal_endpoint_validation(db_session):
    fs, project, category, _, _ = _seed_ledger(db_session)
    payload = schemas.JournalEntryIn(
        kind="ADJUST",
        postings=[
            schemas.JournalPostingIn(budget_id=fs.id, item_project_id=project.id, category_id=category.id, amount=10.0),
        ],
    )
    with pytest.raises(HTTPException):
        _create_journal(db_session, kind=payload.kind, note=None, created_by=None, postings=payload.postings)
