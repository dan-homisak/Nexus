from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import models, models_finance, schemas
from backend.routes_funding import api_attach_line_asset, api_detach_line_asset
from backend.services import funding, tags as tag_service


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


def _seed_structure(session):
    budget = models_finance.FundingSource(
        name="Cobra Retrofit FY25",
        type="COST_CENTER",
        owner="alice",
        is_cost_center=False,
        description="Core program budget",
        budget_amount_cache=Decimal("300"),
    )
    session.add(budget)
    session.flush()

    project = models.Project(
        name="PM11",
        budget_id=budget.id,
        portfolio_id=budget.id,
        description="Packaging line PM11",
    )
    session.add(project)
    session.flush()

    line_asset = models.LineAsset(name="STA03")
    session.add(line_asset)
    session.flush()
    session.add(models.ItemProjectLineAsset(item_project_id=project.id, line_asset_id=line_asset.id))

    root = models.Category(
        name="Infrastructure",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=None,
        is_leaf=False,
        amount_leaf=None,
        rollup_amount=Decimal("300"),
        path_depth=0,
        path_ids=[],
        path_names=[],
    )
    session.add(root)
    session.flush()
    root.path_ids = [root.id]
    root.path_names = [root.name]

    leaf1 = models.Category(
        name="Compute",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=root.id,
        is_leaf=True,
        amount_leaf=Decimal("200"),
        rollup_amount=Decimal("200"),
        path_depth=1,
        path_ids=[root.id, 0],
        path_names=[root.name, "Compute"],
    )
    session.add(leaf1)
    session.flush()
    leaf1.path_ids = [root.id, leaf1.id]
    leaf1.path_names = [root.name, leaf1.name]

    leaf2 = models.Category(
        name="Storage",
        project_id=project.id,
        budget_id=budget.id,
        parent_id=root.id,
        is_leaf=True,
        amount_leaf=Decimal("100"),
        rollup_amount=Decimal("100"),
        path_depth=1,
        path_ids=[root.id, 0],
        path_names=[root.name, "Storage"],
    )
    session.add(leaf2)
    session.flush()
    leaf2.path_ids = [root.id, leaf2.id]
    leaf2.path_names = [root.name, leaf2.name]

    entry = models.Entry(
        kind="expense",
        amount=300.0,
        portfolio_id=budget.id,
        project_id=project.id,
        item_project_id=project.id,
        category_id=leaf1.id,
    )
    session.add(entry)
    session.flush()

    allocation = models.Allocation(
        entry_id=entry.id,
        item_project_id=project.id,
        category_id=leaf1.id,
        budget_id=budget.id,
        amount=Decimal("300"),
    )
    session.add(allocation)
    session.commit()

    program_tag = tag_service.create_tag(session, name="program_cobra", color="#123456", description=None, actor="tester")
    tag_service.assign_tag(
        session,
        tag_id=program_tag.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )
    tag_service.rebuild_effective_tags(session, actor="tester")

    session.refresh(budget)
    session.refresh(project)
    session.refresh(root)
    session.refresh(leaf1)
    session.refresh(leaf2)

    return {
        "budget": budget,
        "project": project,
        "root": root,
        "leaf1": leaf1,
        "leaf2": leaf2,
        "line_asset": line_asset,
    }


def test_budget_tree_and_stats(db_session):
    data = _seed_structure(db_session)

    records = funding.budget_tree(db_session, data["budget"].id, project_id=None, include={"tags", "paths", "assets"})
    assert records[0]["type"] == "budget"
    assert records[0]["tags"]["direct"][0]["name"] == "program_cobra"

    project_nodes = [node for node in records if node["type"] == "project"]
    assert len(project_nodes) == 1
    assert project_nodes[0]["assets"]["count"] == 1

    leaf_nodes = [node for node in records if node["type"] == "category" and node["is_leaf"]]
    assert {node["name"] for node in leaf_nodes} == {"Compute", "Storage"}

    budgets = funding.list_budgets(db_session, q=None, is_cost_center=None, owner=None, ids=None, include={"stats", "tags"})
    stats = budgets[0]["stats"]
    assert stats["category_count"] == 3
    assert stats["leaf_count"] == 2


def test_category_relocation_guard(db_session):
    data = _seed_structure(db_session)

    other_parent = models.Category(
        name="Facilities",
        project_id=data["project"].id,
        budget_id=data["budget"].id,
        parent_id=None,
        is_leaf=False,
        rollup_amount=Decimal("0"),
        path_depth=0,
        path_ids=[],
        path_names=[],
    )
    db_session.add(other_parent)
    db_session.flush()
    other_parent.path_ids = [other_parent.id]
    other_parent.path_names = [other_parent.name]
    db_session.commit()

    result = funding.can_move_category(db_session, data["root"].id, new_parent_id=other_parent.id)
    assert result == {"can_move": False, "reason": "allocations_present", "count": 1}

    with pytest.raises(funding.FundingServiceError) as exc:
        funding.update_category(db_session, data["root"].id, parent_id=other_parent.id)
    assert exc.value.code == "allocations_present"

    orphan = models.Category(
        name="Orphan",
        project_id=data["project"].id,
        budget_id=data["budget"].id,
        parent_id=None,
        is_leaf=True,
        amount_leaf=Decimal("0"),
        rollup_amount=Decimal("0"),
        path_depth=0,
        path_ids=[],
        path_names=[],
    )
    db_session.add(orphan)
    db_session.flush()
    orphan.path_ids = [orphan.id]
    orphan.path_names = [orphan.name]
    db_session.commit()

    result = funding.can_move_category(db_session, orphan.id, new_parent_id=other_parent.id)
    assert result == {"can_move": True, "reason": None, "count": 0}

    updated = funding.update_category(db_session, orphan.id, parent_id=other_parent.id)
    assert updated.parent_id == other_parent.id


def test_category_creation_scope_validation(db_session):
    data = _seed_structure(db_session)
    other_budget = models_finance.FundingSource(name="Packaging FY25", is_cost_center=False)
    db_session.add(other_budget)
    db_session.commit()

    with pytest.raises(funding.FundingServiceError) as exc:
        funding.create_category(
            db_session,
            name="Bad Scope",
            project_id=data["project"].id,
            budget_id=other_budget.id,
            parent_id=data["root"].id,
            is_leaf=False,
            amount_leaf=None,
            description=None,
        )
    assert exc.value.code == "invalid_parent"


def test_attach_detach_line_asset_endpoints(db_session):
    portfolio = models.Portfolio(name="Default Portfolio")
    budget = models_finance.FundingSource(name="Cobra Retrofit", is_cost_center=False)
    db_session.add_all([portfolio, budget])
    db_session.flush()

    project = models.Project(
        name="PM11",
        portfolio_id=portfolio.id,
        budget_id=budget.id,
    )
    asset = models.LineAsset(name="STA03")
    db_session.add_all([project, asset])
    db_session.commit()

    payload = schemas.ItemProjectAssetLink(line_asset_id=asset.id)
    result = api_attach_line_asset(project.id, payload, db=db_session)
    assert result.id == asset.id

    link = db_session.get(models.ItemProjectLineAsset, (project.id, asset.id))
    assert link is not None

    repeat = api_attach_line_asset(project.id, payload, db=db_session)
    assert repeat.id == asset.id
    count = db_session.execute(
        select(func.count())
        .select_from(models.ItemProjectLineAsset)
        .where(
            models.ItemProjectLineAsset.item_project_id == project.id,
            models.ItemProjectLineAsset.line_asset_id == asset.id,
        )
    ).scalar_one()
    assert count == 1

    response = api_detach_line_asset(project.id, asset.id, db=db_session)
    assert response == {"ok": True}
    assert db_session.get(models.ItemProjectLineAsset, (project.id, asset.id)) is None

    with pytest.raises(HTTPException) as exc:
        api_detach_line_asset(project.id, asset.id, db=db_session)
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "not_found"


def test_deletion_guards_and_usage(db_session):
    data = _seed_structure(db_session)

    with pytest.raises(funding.FundingServiceError) as exc:
        funding.delete_item_project(db_session, data["project"].id)
    assert exc.value.code == "allocations_present"

    with pytest.raises(funding.FundingServiceError):
        funding.delete_budget(db_session, data["budget"].id)

    usage = tag_service.get_usage(db_session)
    name_map = {item["tag"]["name"] for item in usage}
    assert "program_cobra" in name_map


def test_scoped_rebuild(db_session):
    data = _seed_structure(db_session)

    scoped_tag = tag_service.create_tag(db_session, name="scoped", color=None, description=None, actor="tester")
    tag_service.assign_tag(
        db_session,
        tag_id=scoped_tag.id,
        tag_name=None,
        entity_type="category",
        entity_id=data["leaf2"].id,
        scope=None,
        actor="tester",
    )
    db_session.commit()

    job = tag_service.rebuild_effective_tags(db_session, actor="tester", only_for=f"category:{data['leaf2'].id}")
    assert job.status == "success"

    rows = tag_service.list_effective_tags(db_session, entity_type="category", entity_id=data["leaf2"].id)
    assert any(row["name"] == "scoped" for row in rows)

    other_rows = tag_service.list_effective_tags(db_session, entity_type="category", entity_id=data["leaf1"].id)
    assert all(row["name"] != "scoped" for row in other_rows)
