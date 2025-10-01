from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import models, models_finance
from backend.services import funding


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _create_budget_and_project(session):
    budget = models_finance.FundingSource(name="Investigate", type="COST_CENTER", is_cost_center=False)
    session.add(budget)
    session.flush()
    project = models.Project(name="Tree", budget_id=budget.id, portfolio_id=budget.id)
    session.add(project)
    session.commit()
    return budget, project


def test_parent_leaf_flags_after_child_lifecycle(db_session):
    budget, project = _create_budget_and_project(db_session)

    parent = funding.create_category(
        db_session,
        name="Parent",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=None,
        is_leaf=False,
        amount_leaf=None,
        description=None,
    )
    child = funding.create_category(
        db_session,
        name="Leaf",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=parent.id,
        is_leaf=True,
        amount_leaf=Decimal("5"),
        description=None,
    )

    db_session.refresh(parent)
    assert parent.is_leaf is False
    assert parent.amount_leaf is None

    tree = funding.budget_tree(db_session, budget.id, project_id=None, include=set())
    parent_node = next(node for node in tree if node["type"] == "category" and node["id"] == parent.id)
    child_node = next(node for node in tree if node["type"] == "category" and node["id"] == child.id)
    assert parent_node["is_leaf"] is False
    assert child_node["is_leaf"] is True

    funding.delete_category(db_session, child.id)
    db_session.refresh(parent)
    assert parent.is_leaf is True
    assert parent.amount_leaf == Decimal("0")

    tree_after_delete = funding.budget_tree(db_session, budget.id, project_id=None, include=set())
    parent_after_delete = next(node for node in tree_after_delete if node["type"] == "category" and node["id"] == parent.id)
    assert parent_after_delete["is_leaf"] is True
    assert parent_after_delete["rollup_amount"] == 0.0


def test_update_category_parent_recalculates_flags(db_session):
    budget, project = _create_budget_and_project(db_session)

    parent = funding.create_category(
        db_session,
        name="Parent",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=None,
        is_leaf=False,
        amount_leaf=None,
        description=None,
    )
    child = funding.create_category(
        db_session,
        name="Leaf",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=parent.id,
        is_leaf=True,
        amount_leaf=Decimal("12"),
        description=None,
    )

    other_group = funding.create_category(
        db_session,
        name="Group",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=None,
        is_leaf=False,
        amount_leaf=None,
        description=None,
    )

    funding.update_category(db_session, child.id, parent_id=other_group.id)
    db_session.refresh(parent)
    db_session.refresh(other_group)

    assert other_group.is_leaf is False
    assert parent.is_leaf is True
    assert parent.amount_leaf == Decimal("0")
    assert parent.rollup_amount == Decimal("0")
    assert other_group.rollup_amount == Decimal("12")

    tree = funding.budget_tree(db_session, budget.id, project_id=None, include=set())
    parent_node = next(node for node in tree if node["type"] == "category" and node["id"] == parent.id)
    other_group_node = next(node for node in tree if node["type"] == "category" and node["id"] == other_group.id)
    child_node = next(node for node in tree if node["type"] == "category" and node["id"] == child.id)

    assert parent_node["is_leaf"] is True
    assert other_group_node["is_leaf"] is False
    assert child_node["parent_id"] == other_group.id
    assert other_group_node["rollup_amount"] == 12.0


def test_first_child_inherits_parent_amount(db_session):
    budget, project = _create_budget_and_project(db_session)

    parent = funding.create_category(
        db_session,
        name="Parent",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=None,
        is_leaf=True,
        amount_leaf=Decimal("120"),
        description=None,
    )

    first_child = funding.create_category(
        db_session,
        name="Child1",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=parent.id,
        is_leaf=True,
        amount_leaf=None,
        description=None,
    )

    db_session.refresh(parent)
    db_session.refresh(first_child)

    assert parent.is_leaf is False
    assert parent.amount_leaf is None
    assert parent.rollup_amount == Decimal("120")
    assert first_child.amount_leaf == Decimal("120")
    assert first_child.rollup_amount == Decimal("120")

    second_child = funding.create_category(
        db_session,
        name="Child2",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=parent.id,
        is_leaf=True,
        amount_leaf=None,
        description=None,
    )

    db_session.refresh(second_child)
    assert second_child.amount_leaf == Decimal("0")
    assert parent.rollup_amount == Decimal("120")

    tree = funding.budget_tree(db_session, budget.id, project_id=None, include=set())
    parent_node = next(node for node in tree if node["type"] == "category" and node["id"] == parent.id)
    assert parent_node["is_leaf"] is False
    assert parent_node["rollup_amount"] == 120.0
