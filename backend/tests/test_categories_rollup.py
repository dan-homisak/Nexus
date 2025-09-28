from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import models, models_finance  # noqa: F401 ensure metadata is loaded
from backend.scripts.reconcile_ledgers import reconcile_ledgers
from importlib import import_module

_migration = import_module("backend.migrations.versions.20240709_01_phase1_schema")
TRIGGER_CATEGORY_AMOUNT_GUARD = _migration.TRIGGER_CATEGORY_AMOUNT_GUARD
TRIGGER_CATEGORY_AFTER_INSERT = _migration.TRIGGER_CATEGORY_AFTER_INSERT
TRIGGER_CATEGORY_AFTER_DELETE = _migration.TRIGGER_CATEGORY_AFTER_DELETE
TRIGGER_CATEGORY_AFTER_UPDATE = _migration.TRIGGER_CATEGORY_AFTER_UPDATE
TRIGGER_ALLOCATIONS_GUARD_INSERT = _migration.TRIGGER_ALLOCATIONS_GUARD_INSERT
TRIGGER_ALLOCATIONS_GUARD_UPDATE = _migration.TRIGGER_ALLOCATIONS_GUARD_UPDATE
_backfill_allocations = _migration._backfill_allocations


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # install triggers defined in migration
    with engine.begin() as conn:
        for trigger_sql in (
            TRIGGER_CATEGORY_AMOUNT_GUARD,
            TRIGGER_CATEGORY_AFTER_INSERT,
            TRIGGER_CATEGORY_AFTER_DELETE,
            TRIGGER_CATEGORY_AFTER_UPDATE,
            TRIGGER_ALLOCATIONS_GUARD_INSERT,
            TRIGGER_ALLOCATIONS_GUARD_UPDATE,
        ):
            conn.exec_driver_sql(trigger_sql)
    SessionLocal = sessionmaker(bind=engine, future=True)
    with SessionLocal() as session:
        yield session
        session.rollback()


def _seed_budget_hierarchy(session):
    fs = models_finance.FundingSource(name="Budget A", type="CAR", is_cost_center=False)
    portfolio = models.Portfolio(name="Portfolio A")
    session.add_all([fs, portfolio])
    session.flush()

    project = models.Project(
        name="Item X",
        portfolio_id=portfolio.id,
        budget_id=fs.id,
    )
    session.add(project)
    session.flush()

    root = models.Category(name="Root", budget_id=fs.id, item_project_id=project.id)
    session.add(root)
    session.flush()

    leaf = models.Category(
        name="Leaf",
        parent_id=root.id,
        budget_id=fs.id,
        item_project_id=project.id,
        amount_leaf=Decimal("100"),
    )
    session.add(leaf)
    session.commit()
    return fs, project, root, leaf


def test_leaf_enforcement_and_rollups(session):
    fs, project, root, leaf = _seed_budget_hierarchy(session)

    session.refresh(root)
    session.refresh(leaf)
    session.refresh(fs)

    assert leaf.is_leaf is True
    assert root.is_leaf is False
    assert Decimal(str(root.rollup_amount)) == Decimal("100")
    assert Decimal(str(fs.budget_amount_cache)) == Decimal("100")

    # Updating the leaf amount cascades rollup + cache
    leaf.amount_leaf = Decimal("150")
    session.add(leaf)
    session.commit()
    session.refresh(root)
    session.refresh(fs)
    assert Decimal(str(root.rollup_amount)) == Decimal("150")
    assert Decimal(str(fs.budget_amount_cache)) == Decimal("150")

    # Parent categories cannot hold direct amounts
    root.amount_leaf = Decimal("10")
    session.add(root)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_allocation_guards(session):
    fs, project, root, leaf = _seed_budget_hierarchy(session)

    entry = models.Entry(
        kind="expense",
        amount=200.0,
        portfolio_id=project.portfolio_id,
        project_id=project.id,
        item_project_id=project.id,
        category_id=leaf.id,
    )
    session.add(entry)
    session.commit()

    # Non-leaf category should be rejected
    bad_alloc = models.Allocation(
        entry_id=entry.id,
        item_project_id=project.id,
        category_id=root.id,
        budget_id=fs.id,
        amount=Decimal("50"),
    )
    session.add(bad_alloc)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Leaf but mismatched project should be rejected
    other_project = models.Project(
        name="Item Y",
        portfolio_id=project.portfolio_id,
        budget_id=fs.id,
    )
    session.add(other_project)
    session.flush()
    mismatch_alloc = models.Allocation(
        entry_id=entry.id,
        item_project_id=other_project.id,
        category_id=leaf.id,
        budget_id=fs.id,
        amount=Decimal("50"),
    )
    session.add(mismatch_alloc)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_reconciler_idempotent(session):
    fs, project, root, leaf = _seed_budget_hierarchy(session)
    # Corrupt cached data intentionally
    session.execute(text("UPDATE categories SET rollup_amount = 0, path_ids = NULL, path_names = NULL"))
    session.execute(text("UPDATE funding_sources SET budget_amount_cache = NULL"))
    session.commit()

    stats_first = reconcile_ledgers(session)
    stats_second = reconcile_ledgers(session)

    session.refresh(root)
    session.refresh(leaf)
    session.refresh(fs)

    assert Decimal(str(root.rollup_amount)) == Decimal("100")
    assert Decimal(str(fs.budget_amount_cache)) == Decimal("100")
    assert stats_first["budgets_reconciled"] == stats_second["budgets_reconciled"]


def test_allocation_backfill_helper(session):
    fs, project, root, leaf = _seed_budget_hierarchy(session)

    entry = models.Entry(
        kind="expense",
        amount=250.0,
        portfolio_id=project.portfolio_id,
        project_id=project.id,
        item_project_id=project.id,
        category_id=leaf.id,
    )
    session.add(entry)
    session.commit()

    created = _backfill_allocations(session)
    session.refresh(entry)

    assert created == 1
    allocation = session.execute(
        text("SELECT item_project_id, category_id, budget_id, amount FROM allocations WHERE entry_id = :eid"),
        {"eid": entry.id},
    ).mappings().one()
    assert allocation["item_project_id"] == project.id
    assert allocation["category_id"] == leaf.id
    assert allocation["budget_id"] == fs.id
    assert Decimal(str(allocation["amount"])) == Decimal("250")
