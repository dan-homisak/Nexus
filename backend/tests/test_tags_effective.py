from __future__ import annotations

from typing import Iterable

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import models, models_finance
from backend.services import tags as tag_service


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_hierarchy(session):
    budget = models_finance.FundingSource(name="cobra", type="COST_CENTER", is_cost_center=False)
    session.add(budget)
    session.flush()
    project = models.Project(name="proj-a", portfolio_id=1, budget_id=budget.id)
    session.add(project)
    session.flush()
    cat_root = models.Category(
        name="root",
        budget_id=budget.id,
        item_project_id=project.id,
        is_leaf=False,
    )
    session.add(cat_root)
    session.flush()
    cat_parent = models.Category(
        name="parent",
        parent_id=cat_root.id,
        budget_id=budget.id,
        item_project_id=project.id,
        is_leaf=False,
    )
    session.add(cat_parent)
    session.flush()
    cat_leaf = models.Category(
        name="leaf",
        parent_id=cat_parent.id,
        budget_id=budget.id,
        item_project_id=project.id,
        is_leaf=True,
    )
    session.add(cat_leaf)
    session.flush()
    line_asset = models.LineAsset(name="asset-1")
    session.add(line_asset)
    session.flush()
    session.add(
        models.ItemProjectLineAsset(item_project_id=project.id, line_asset_id=line_asset.id)
    )
    session.commit()
    return budget, project, cat_parent, cat_leaf, line_asset


def _names(rows: Iterable[dict]) -> set[tuple[str, str]]:
    return {(row["tag_name"], row["source"]) for row in rows}


def test_tag_crud_and_assignments(db_session):
    budget, *_ = _seed_hierarchy(db_session)

    created = tag_service.create_tag(
        db_session,
        name="Budget_Tag",
        color="#123456",
        description="budget scope",
        actor="tester",
    )
    assert created.name == "budget_tag"
    assert created.color == "#123456"

    updated = tag_service.update_tag(
        db_session,
        created,
        color="#654321",
        description="updated",
        is_deprecated=None,
        actor="tester",
    )
    assert updated.color == "#654321"
    assert updated.description == "updated"

    renamed = tag_service.rename_tag(db_session, created, name="bud_tag", actor="tester")
    assert renamed.name == "bud_tag"

    assignment = tag_service.assign_tag(
        db_session,
        tag_id=renamed.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )
    assert assignment.scope == ""

    tag_service.unassign_tag(
        db_session,
        tag_id=renamed.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )
    remaining = db_session.execute(
        select(models.TagAssignment).where(models.TagAssignment.tag_id == renamed.id)
    ).scalars().all()
    assert remaining == []


def test_merge_tags_moves_assignments(db_session):
    budget, *_ = _seed_hierarchy(db_session)
    tag_a = tag_service.create_tag(db_session, name="alpha", color=None, description=None, actor="tester")
    tag_b = tag_service.create_tag(db_session, name="beta", color=None, description=None, actor="tester")

    tag_service.assign_tag(
        db_session,
        tag_id=tag_a.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )
    tag_service.assign_tag(
        db_session,
        tag_id=tag_b.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )

    merged = tag_service.merge_tags(db_session, source=tag_a, target=tag_b, actor="tester")
    assert merged.id == tag_b.id
    assert tag_a.is_deprecated is True

    assignments = db_session.execute(
        select(models.TagAssignment).where(models.TagAssignment.entity_type == "budget")
    ).scalars().all()
    assert len(assignments) == 1
    assert assignments[0].tag_id == tag_b.id


def test_effective_tag_rebuild(db_session):
    budget, project, cat_parent, cat_leaf, line_asset = _seed_hierarchy(db_session)

    t_budget = tag_service.create_tag(db_session, name="budget", color=None, description=None, actor="tester")
    t_item = tag_service.create_tag(db_session, name="item", color=None, description=None, actor="tester")
    t_parent = tag_service.create_tag(db_session, name="parenttag", color=None, description=None, actor="tester")
    t_leaf = tag_service.create_tag(db_session, name="leaf", color=None, description=None, actor="tester")
    t_line = tag_service.create_tag(db_session, name="line", color=None, description=None, actor="tester")

    tag_service.assign_tag(
        db_session,
        tag_id=t_budget.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )
    tag_service.assign_tag(
        db_session,
        tag_id=t_item.id,
        tag_name=None,
        entity_type="item_project",
        entity_id=project.id,
        scope=None,
        actor="tester",
    )
    tag_service.assign_tag(
        db_session,
        tag_id=t_parent.id,
        tag_name=None,
        entity_type="category",
        entity_id=cat_parent.id,
        scope=None,
        actor="tester",
    )
    tag_service.assign_tag(
        db_session,
        tag_id=t_leaf.id,
        tag_name=None,
        entity_type="category",
        entity_id=cat_leaf.id,
        scope=None,
        actor="tester",
    )
    tag_service.assign_tag(
        db_session,
        tag_id=t_line.id,
        tag_name=None,
        entity_type="line_asset",
        entity_id=line_asset.id,
        scope=None,
        actor="tester",
    )

    job = tag_service.rebuild_effective_tags(db_session, actor="tester")
    assert job.status == "success"

    budget_rows = list(tag_service.list_effective_tags(db_session, entity_type="budget", entity_id=budget.id))
    assert _names(budget_rows) == {("budget", "direct")}

    project_rows = list(tag_service.list_effective_tags(db_session, entity_type="item_project", entity_id=project.id))
    assert _names(project_rows) == {("item", "direct"), ("budget", "inherit:budget")}

    leaf_rows = list(tag_service.list_effective_tags(db_session, entity_type="category", entity_id=cat_leaf.id))
    assert {row["tag_name"] for row in leaf_rows} == {"leaf", "parenttag", "item", "budget"}
    sources = {row["tag_name"]: row["source"] for row in leaf_rows}
    assert sources["leaf"] == "direct"
    assert sources["parenttag"] == "inherit:category"
    assert sources["item"] == "inherit:item_project"
    assert sources["budget"] == "inherit:budget"

    parent_rows = list(tag_service.list_effective_tags(db_session, entity_type="category", entity_id=cat_parent.id))
    assert _names(parent_rows) == {("parenttag", "direct"), ("item", "inherit:item_project"), ("budget", "inherit:budget")}

    line_rows = list(tag_service.list_effective_tags(db_session, entity_type="line_asset", entity_id=line_asset.id))
    assert {row["tag_name"] for row in line_rows} == {"line", "item", "budget"}
    src_map = {row["tag_name"]: row["source"] for row in line_rows}
    assert src_map["line"] == "direct"
    assert src_map["item"] == "inherit:item_project"
    assert src_map["budget"] == "inherit:budget"

    # Ensure path_ids recorded for category inheritance
    cat_inherit = next(row for row in leaf_rows if row["tag_name"] == "parenttag")
    assert cat_inherit["path_ids"] == f"[{cat_parent.id}]"


def test_background_job_and_audit(db_session):
    budget, *_ = _seed_hierarchy(db_session)
    tag = tag_service.create_tag(db_session, name="audit", color=None, description=None, actor="tester")
    tag_service.assign_tag(
        db_session,
        tag_id=tag.id,
        tag_name=None,
        entity_type="budget",
        entity_id=budget.id,
        scope=None,
        actor="tester",
    )

    job = tag_service.rebuild_effective_tags(db_session, actor="tester")
    stored = tag_service.get_job(db_session, job.id)
    assert stored is not None
    assert stored.status == "success"

    events = db_session.execute(select(models.AuditEvent).order_by(models.AuditEvent.id)).scalars().all()
    event_types = [e.event_type for e in events]
    assert "job.start" in event_types and "job.finish" in event_types
