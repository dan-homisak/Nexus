"""Funding domain service helpers for budgets, projects, categories, and assets."""

from __future__ import annotations

from datetime import date as DateType, datetime as DateTimeType
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import distinct, func, select, text
from sqlalchemy.orm import Session

from .. import models, models_finance
from . import tags as tag_service


class FundingServiceError(ValueError):
    """Service-level exception with an optional error code."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


TagBundle = Dict[str, List[Dict[str, Any]]]
IncludeSet = Set[str]


def _float(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


def _tag_bundle(db: Session, entity_type: str, entity_id: int) -> TagBundle:
    return tag_service.get_tag_groups(db, entity_type=entity_type, entity_id=entity_id)


def _build_in_clause(prefix: str, ids: Iterable[int]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    tokens: List[str] = []
    for idx, value in enumerate(ids):
        key = f"{prefix}_{idx}"
        params[key] = value
        tokens.append(f":{key}")
    return ", ".join(tokens), params


def _budget_stats(db: Session, budget_ids: List[int]) -> Dict[int, Dict[str, int]]:
    if not budget_ids:
        return {}
    stats: Dict[int, Dict[str, int]] = {bid: {
        "category_count": 0,
        "leaf_count": 0,
        "entry_count": 0,
        "allocation_count": 0,
    } for bid in budget_ids}

    category_counts = db.execute(
        select(models.Category.budget_id, func.count())
        .where(models.Category.budget_id.in_(budget_ids))
        .group_by(models.Category.budget_id)
    )
    for budget_id, count in category_counts:
        stats[budget_id]["category_count"] = count

    leaf_counts = db.execute(
        select(models.Category.budget_id, func.count())
        .where(models.Category.budget_id.in_(budget_ids), models.Category.is_leaf.is_(True))
        .group_by(models.Category.budget_id)
    )
    for budget_id, count in leaf_counts:
        stats[budget_id]["leaf_count"] = count

    allocation_counts = db.execute(
        select(
            models.Allocation.budget_id,
            func.count().label("allocations"),
            func.count(distinct(models.Allocation.entry_id)).label("entries"),
        )
        .where(models.Allocation.budget_id.in_(budget_ids))
        .group_by(models.Allocation.budget_id)
    )
    for budget_id, allocs, entries in allocation_counts:
        stats[budget_id]["allocation_count"] = allocs
        stats[budget_id]["entry_count"] = entries

    return stats


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def list_budgets(
    db: Session,
    *,
    q: Optional[str] = None,
    is_cost_center: Optional[bool] = None,
    owner: Optional[str] = None,
    ids: Optional[List[int]] = None,
    include: IncludeSet,
) -> List[Dict[str, Any]]:
    stmt = select(models_finance.FundingSource)
    if ids:
        stmt = stmt.where(models_finance.FundingSource.id.in_(ids))
    if q:
        stmt = stmt.where(func.lower(models_finance.FundingSource.name).like(f"%{q.lower()}%"))
    if is_cost_center is not None:
        stmt = stmt.where(models_finance.FundingSource.is_cost_center.is_(is_cost_center))
    if owner:
        stmt = stmt.where(func.lower(models_finance.FundingSource.owner or "").like(f"%{owner.lower()}%"))

    budgets = db.execute(stmt.order_by(models_finance.FundingSource.name.asc())).scalars().all()
    budget_ids = [b.id for b in budgets]
    stats_map = _budget_stats(db, budget_ids) if "stats" in include else {}

    items: List[Dict[str, Any]] = []
    for budget in budgets:
        payload: Dict[str, Any] = {
            "id": budget.id,
            "name": budget.name,
            "owner": budget.owner,
            "is_cost_center": budget.is_cost_center,
            "closure_date": budget.closure_date,
            "description": budget.description,
            "budget_amount_cache": _float(budget.budget_amount_cache),
            "created_at": budget.created_at,
            "updated_at": budget.updated_at,
        }
        if "stats" in include:
            payload["stats"] = stats_map.get(budget.id, {
                "category_count": 0,
                "leaf_count": 0,
                "entry_count": 0,
                "allocation_count": 0,
            })
        if "tags" in include:
            payload["tags"] = _tag_bundle(db, "budget", budget.id)
        items.append(payload)
    return items


def get_budget(
    db: Session,
    budget_id: int,
    *,
    include: IncludeSet,
) -> Dict[str, Any]:
    budget = db.get(models_finance.FundingSource, budget_id)
    if not budget:
        raise FundingServiceError("budget not found", code="not_found")
    record = list_budgets(db, ids=[budget_id], q=None, is_cost_center=None, owner=None, include=include)
    return record[0]


def create_budget(
    db: Session,
    *,
    name: str,
    owner: Optional[str],
    is_cost_center: bool,
    closure_date: Optional[str],
    description: Optional[str],
) -> models_finance.FundingSource:
    parsed_closure_date = None
    if closure_date not in (None, ""):
        try:
            parsed_closure_date = DateType.fromisoformat(closure_date)
        except ValueError as exc:
            raise FundingServiceError("invalid closure_date format", code="invalid_closure_date") from exc
    now = DateTimeType.utcnow()
    budget = models_finance.FundingSource(
        name=name,
        owner=owner,
        is_cost_center=is_cost_center,
        closure_date=parsed_closure_date,
        description=description,
        created_at=now,
        updated_at=now,
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


def _ensure_budget_can_unset_cost_center(db: Session, budget_id: int) -> None:
    has_leaf_amount = db.execute(
        select(func.count())
        .select_from(models.Category)
        .where(
            models.Category.budget_id == budget_id,
            models.Category.is_leaf.is_(True),
            models.Category.amount_leaf.is_not(None),
        )
    ).scalar()
    if not has_leaf_amount:
        raise FundingServiceError(
            "Budget requires leaf category amounts before disabling cost center",
            code="missing_leaf_amounts",
        )


def update_budget(
    db: Session,
    budget_id: int,
    *,
    name: Optional[str] = None,
    owner: Optional[str] = None,
    is_cost_center: Optional[bool] = None,
    closure_date: Optional[str] = None,
    description: Optional[str] = None,
) -> models_finance.FundingSource:
    budget = db.get(models_finance.FundingSource, budget_id)
    if not budget:
        raise FundingServiceError("budget not found", code="not_found")

    if is_cost_center is not None and not is_cost_center and budget.is_cost_center:
        _ensure_budget_can_unset_cost_center(db, budget_id)
        budget.is_cost_center = False
    elif is_cost_center is not None:
        budget.is_cost_center = is_cost_center

    if name is not None:
        budget.name = name
    if owner is not None:
        budget.owner = owner
    if closure_date is not None:
        if closure_date == "" or closure_date is None:
            budget.closure_date = None
        else:
            try:
                budget.closure_date = DateType.fromisoformat(closure_date)
            except ValueError as exc:
                raise FundingServiceError("invalid closure_date format", code="invalid_closure_date") from exc
    if description is not None:
        budget.description = description

    db.commit()
    db.refresh(budget)
    return budget


def delete_budget(db: Session, budget_id: int) -> None:
    budget = db.get(models_finance.FundingSource, budget_id)
    if not budget:
        raise FundingServiceError("budget not found", code="not_found")
    category_count = db.execute(
        select(func.count()).where(models.Category.budget_id == budget_id)
    ).scalar()
    allocation_count = db.execute(
        select(func.count()).where(models.Allocation.budget_id == budget_id)
    ).scalar()
    if category_count:
        raise FundingServiceError("budget has categories", code="categories_present")
    if allocation_count:
        raise FundingServiceError("budget has allocations", code="allocations_present")
    db.delete(budget)
    db.commit()


# ---------------------------------------------------------------------------
# Item Projects (projects)
# ---------------------------------------------------------------------------


def list_item_projects(
    db: Session,
    *,
    budget_id: Optional[int] = None,
    q: Optional[str] = None,
    ids: Optional[List[int]] = None,
    include: IncludeSet,
) -> List[Dict[str, Any]]:
    stmt = select(models.Project)
    if ids:
        stmt = stmt.where(models.Project.id.in_(ids))
    if budget_id is not None:
        stmt = stmt.where(models.Project.budget_id == budget_id)
    if q:
        stmt = stmt.where(func.lower(models.Project.name).like(f"%{q.lower()}%"))

    projects = db.execute(stmt.order_by(models.Project.name.asc())).scalars().all()

    # Precompute rollups
    project_ids = [p.id for p in projects]
    rollups: Dict[int, float] = {}
    if project_ids:
        rows = db.execute(
            select(models.Category.item_project_id, func.coalesce(func.sum(models.Category.amount_leaf), 0.0))
            .where(models.Category.item_project_id.in_(project_ids), models.Category.is_leaf.is_(True))
            .group_by(models.Category.item_project_id)
        )
        for pid, amount in rows:
            rollups[pid] = float(amount or 0)

    assets_map: Dict[int, List[Dict[str, Any]]] = {}
    if "assets" in include and project_ids:
        rows = db.execute(
            select(
                models.ItemProjectLineAsset.item_project_id,
                models.LineAsset.id,
                models.LineAsset.name,
            )
            .join(models.LineAsset, models.LineAsset.id == models.ItemProjectLineAsset.line_asset_id)
            .where(models.ItemProjectLineAsset.item_project_id.in_(project_ids))
            .order_by(models.LineAsset.name.asc())
        )
        for project_id, asset_id, name in rows:
            assets_map.setdefault(project_id, []).append({"id": asset_id, "name": name})

    items: List[Dict[str, Any]] = []
    for project in projects:
        payload: Dict[str, Any] = {
            "id": project.id,
            "name": project.name,
            "budget_id": project.budget_id,
            "description": project.description,
            "legacy_portfolio_id": project.legacy_portfolio_id,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "rollup_amount": rollups.get(project.id, 0.0),
        }
        if "tags" in include:
            payload["tags"] = _tag_bundle(db, "item_project", project.id)
        if "assets" in include:
            assets = assets_map.get(project.id, [])
            payload["assets"] = {
                "count": len(assets),
                "items": assets,
            }
        items.append(payload)
    return items


def get_item_project(db: Session, item_project_id: int, *, include: IncludeSet) -> Dict[str, Any]:
    result = list_item_projects(db, ids=[item_project_id], include=include, budget_id=None, q=None)
    if not result:
        raise FundingServiceError("item_project not found", code="not_found")
    return result[0]


def create_item_project(
    db: Session,
    *,
    budget_id: int,
    name: str,
    description: Optional[str],
) -> models.Project:
    now = DateTimeType.utcnow()
    project = models.Project(
        budget_id=budget_id,
        name=name,
        description=description,
        portfolio_id=budget_id,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _has_allocations_for_project(db: Session, project_id: int) -> bool:
    count = db.execute(
        select(func.count()).where(models.Allocation.item_project_id == project_id)
    ).scalar()
    return bool(count)


def update_item_project(
    db: Session,
    project_id: int,
    *,
    name: Optional[str],
    description: Optional[str],
) -> models.Project:
    project = db.get(models.Project, project_id)
    if not project:
        raise FundingServiceError("item_project not found", code="not_found")
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    db.commit()
    db.refresh(project)
    return project


def delete_item_project(db: Session, project_id: int) -> None:
    project = db.get(models.Project, project_id)
    if not project:
        raise FundingServiceError("item_project not found", code="not_found")
    if _has_allocations_for_project(db, project_id):
        raise FundingServiceError("item_project has allocations", code="allocations_present")
    db.delete(project)
    db.commit()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _subtree_category_ids(db: Session, category_id: int) -> List[int]:
    rows = db.execute(
        text(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM categories WHERE id = :root
                UNION ALL
                SELECT c.id FROM categories AS c JOIN subtree AS s ON c.parent_id = s.id
            )
            SELECT id FROM subtree
            """
        ),
        {"root": category_id},
    )
    return [row[0] for row in rows]


def _subtree_allocation_count(db: Session, category_id: int) -> int:
    result = db.execute(
        text(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM categories WHERE id = :root
                UNION ALL
                SELECT c.id FROM categories AS c JOIN subtree AS s ON c.parent_id = s.id
            )
            SELECT COUNT(*) FROM allocations WHERE category_id IN (SELECT id FROM subtree)
            """
        ),
        {"root": category_id},
    )
    return result.scalar_one()


def list_categories(
    db: Session,
    *,
    budget_id: Optional[int] = None,
    project_id: Optional[int] = None,
    parent_id: Optional[int] = None,
    q: Optional[str] = None,
    ids: Optional[List[int]] = None,
    include: IncludeSet,
) -> List[Dict[str, Any]]:
    stmt = select(models.Category)
    if ids:
        stmt = stmt.where(models.Category.id.in_(ids))
    if budget_id is not None:
        stmt = stmt.where(models.Category.budget_id == budget_id)
    if project_id is not None:
        stmt = stmt.where(models.Category.item_project_id == project_id)
    if parent_id is not None:
        stmt = stmt.where(models.Category.parent_id == parent_id)
    if q:
        stmt = stmt.where(func.lower(models.Category.name).like(f"%{q.lower()}%"))

    categories = db.execute(stmt.order_by(models.Category.path_depth.asc(), models.Category.name.asc())).scalars().all()

    items: List[Dict[str, Any]] = []
    for category in categories:
        payload: Dict[str, Any] = {
            "id": category.id,
            "name": category.name,
            "parent_id": category.parent_id,
            "project_id": category.project_id,
            "budget_id": category.budget_id,
            "is_leaf": category.is_leaf,
            "amount_leaf": _float(category.amount_leaf),
            "rollup_amount": _float(category.rollup_amount),
            "path_depth": category.path_depth,
        }
        if "paths" in include:
            payload["path_ids"] = category.path_ids
            payload["path_names"] = category.path_names
        if "tags" in include:
            payload["tags"] = _tag_bundle(db, "category", category.id)
        items.append(payload)
    return items


def get_category(db: Session, category_id: int, *, include: IncludeSet) -> Dict[str, Any]:
    result = list_categories(db, ids=[category_id], include=include)
    if not result:
        raise FundingServiceError("category not found", code="not_found")
    return result[0]


def _validate_parent(
    db: Session, parent_id: Optional[int], project_id: int, budget_id: int
) -> Optional[models.Category]:
    if parent_id is None:
        return None
    parent = db.get(models.Category, parent_id)
    if not parent:
        raise FundingServiceError("parent category not found", code="invalid_parent")
    if parent.project_id != project_id or parent.budget_id != budget_id:
        raise FundingServiceError("parent category must share budget and project", code="invalid_parent")
    return parent


def _mark_parent_has_children(parent: Optional[models.Category]) -> None:
    if not parent:
        return
    if parent.is_leaf:
        parent.is_leaf = False
        parent.amount_leaf = None


def _refresh_parent_leaf_state(db: Session, parent_id: Optional[int]) -> None:
    if parent_id is None:
        return
    parent = db.get(models.Category, parent_id)
    if not parent:
        return
    child_count = db.execute(
        select(func.count()).where(models.Category.parent_id == parent_id)
    ).scalar()
    if not child_count:
        parent.is_leaf = True
        if parent.amount_leaf is None:
            parent.amount_leaf = Decimal("0")
    else:
        parent.is_leaf = False
        parent.amount_leaf = None


def create_category(
    db: Session,
    *,
    name: str,
    project_id: int,
    budget_id: int,
    parent_id: Optional[int],
    is_leaf: bool,
    amount_leaf: Optional[Decimal],
    description: Optional[str],
) -> models.Category:
    parent = _validate_parent(db, parent_id, project_id, budget_id)
    if not is_leaf:
        amount_leaf = None
    elif amount_leaf is not None and not isinstance(amount_leaf, Decimal):
        amount_leaf = Decimal(str(amount_leaf))
    category = models.Category(
        name=name,
        project_id=project_id,
        budget_id=budget_id,
        parent_id=parent_id,
        is_leaf=is_leaf,
        amount_leaf=amount_leaf,
        description=description,
    )
    db.add(category)
    _mark_parent_has_children(parent)
    db.commit()
    db.refresh(category)
    return category


def _assert_no_subtree_allocations(db: Session, category_id: int) -> None:
    count = _subtree_allocation_count(db, category_id)
    if count:
        raise FundingServiceError("category subtree has allocations", code="allocations_present")


def update_category(
    db: Session,
    category_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parent_id: Optional[int] = None,
    project_id: Optional[int] = None,
    budget_id: Optional[int] = None,
    is_leaf: Optional[bool] = None,
    amount_leaf: Optional[Decimal] = None,
) -> models.Category:
    category = db.get(models.Category, category_id)
    if not category:
        raise FundingServiceError("category not found", code="not_found")

    target_project = project_id if project_id is not None else category.project_id
    target_budget = budget_id if budget_id is not None else category.budget_id

    # Parent change
    if parent_id is not None and parent_id != category.parent_id:
        if parent_id == category.id:
            raise FundingServiceError("category cannot be its own parent", code="invalid_parent")
        _assert_no_subtree_allocations(db, category_id)
        old_parent_id = category.parent_id
        new_parent = _validate_parent(db, parent_id, target_project, target_budget)
        category.parent_id = parent_id
        db.flush()
        _mark_parent_has_children(new_parent)
        _refresh_parent_leaf_state(db, old_parent_id)
    elif parent_id is None and category.parent_id is not None:
        _assert_no_subtree_allocations(db, category_id)
        old_parent_id = category.parent_id
        category.parent_id = None
        db.flush()
        _refresh_parent_leaf_state(db, old_parent_id)

    # Budget/project changes
    if (project_id is not None and project_id != category.project_id) or (
        budget_id is not None and budget_id != category.budget_id
    ):
        _assert_no_subtree_allocations(db, category_id)
        target_project = project_id if project_id is not None else category.project_id
        target_budget = budget_id if budget_id is not None else category.budget_id
        ids = _subtree_category_ids(db, category_id)
        clause, params = _build_in_clause("cat_update", ids)
        db.execute(
            text(
                f"UPDATE categories SET project_id = :project_id, budget_id = :budget_id WHERE id IN ({clause})"
            ),
            {**params, "project_id": target_project, "budget_id": target_budget},
        )
        category.project_id = target_project
        category.budget_id = target_budget

    if name is not None:
        category.name = name
    if description is not None:
        category.description = description

    if is_leaf is not None and is_leaf != category.is_leaf:
        if is_leaf:
            child_count = db.execute(
                select(func.count()).where(models.Category.parent_id == category_id)
            ).scalar()
            if child_count:
                raise FundingServiceError(
                    "cannot mark category with children as leaf",
                    code="has_children",
                )
            if amount_leaf is None:
                amount_leaf = Decimal("0")
            elif not isinstance(amount_leaf, Decimal):
                amount_leaf = Decimal(str(amount_leaf))
            category.amount_leaf = amount_leaf
        else:
            category.amount_leaf = None
        category.is_leaf = is_leaf
    elif is_leaf or category.is_leaf:
        if amount_leaf is not None:
            if not isinstance(amount_leaf, Decimal):
                amount_leaf = Decimal(str(amount_leaf))
            category.amount_leaf = amount_leaf

    db.commit()
    _refresh_parent_leaf_state(db, category.parent_id)
    db.refresh(category)
    return category


def delete_category(db: Session, category_id: int) -> None:
    category = db.get(models.Category, category_id)
    if not category:
        raise FundingServiceError("category not found", code="not_found")
    parent_id = category.parent_id
    _assert_no_subtree_allocations(db, category_id)
    ids = _subtree_category_ids(db, category_id)
    clause, params = _build_in_clause("cat_del", ids)
    db.execute(text(f"DELETE FROM categories WHERE id IN ({clause})"), params)
    db.commit()
    _refresh_parent_leaf_state(db, parent_id)


def can_move_category(db: Session, category_id: int, *, new_parent_id: Optional[int]) -> Dict[str, Any]:
    category = db.get(models.Category, category_id)
    if not category:
        raise FundingServiceError("category not found", code="not_found")
    if new_parent_id == category.id:
        raise FundingServiceError("category cannot be its own parent", code="invalid_parent")
    count = _subtree_allocation_count(db, category_id)
    if count:
        return {"can_move": False, "reason": "allocations_present", "count": count}
    if new_parent_id is not None:
        parent = db.get(models.Category, new_parent_id)
        if not parent:
            return {"can_move": False, "reason": "parent_not_found", "count": 0}
        if parent.project_id != category.project_id or parent.budget_id != category.budget_id:
            return {"can_move": False, "reason": "parent_scope_mismatch", "count": 0}
    return {"can_move": True, "reason": None, "count": 0}


# ---------------------------------------------------------------------------
# Line assets
# ---------------------------------------------------------------------------


def list_line_assets(
    db: Session,
    *,
    category_id: Optional[int] = None,
    project_id: Optional[int] = None,
    q: Optional[str] = None,
    ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    stmt = select(models.LineAsset)
    if ids:
        stmt = stmt.where(models.LineAsset.id.in_(ids))
    if q:
        stmt = stmt.where(func.lower(models.LineAsset.name).like(f"%{q.lower()}%"))
    assets = db.execute(stmt.order_by(models.LineAsset.name.asc())).scalars().all()

    if category_id is not None:
        category = db.get(models.Category, category_id)
        if not category:
            raise FundingServiceError("category not found", code="not_found")
        project_id = category.project_id

    allowed_ids: Optional[Set[int]] = None
    if project_id is not None:
        rows = db.execute(
            select(models.ItemProjectLineAsset.line_asset_id).where(
                models.ItemProjectLineAsset.item_project_id == project_id
            )
        ).scalars()
        allowed_ids = set(rows)

    results: List[Dict[str, Any]] = []
    for asset in assets:
        if allowed_ids is not None and asset.id not in allowed_ids:
            continue
        results.append({"id": asset.id, "name": asset.name, "created_at": asset.created_at, "updated_at": asset.updated_at})
    return results


def create_line_asset(db: Session, *, name: str) -> models.LineAsset:
    asset = models.LineAsset(name=name)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def update_line_asset(db: Session, line_asset_id: int, *, name: str) -> models.LineAsset:
    asset = db.get(models.LineAsset, line_asset_id)
    if not asset:
        raise FundingServiceError("line asset not found", code="not_found")
    asset.name = name
    db.commit()
    db.refresh(asset)
    return asset


def delete_line_asset(db: Session, line_asset_id: int) -> None:
    asset = db.get(models.LineAsset, line_asset_id)
    if not asset:
        raise FundingServiceError("line asset not found", code="not_found")
    referencing = db.execute(
        select(func.count()).where(models.ItemProjectLineAsset.line_asset_id == line_asset_id)
    ).scalar()
    if referencing:
        raise FundingServiceError("line asset in use", code="assets_present")
    db.delete(asset)
    db.commit()


def add_line_asset_to_item_project(db: Session, project_id: int, line_asset_id: int) -> models.LineAsset:
    project = db.get(models.Project, project_id)
    if not project:
        raise FundingServiceError("item project not found", code="not_found")
    asset = db.get(models.LineAsset, line_asset_id)
    if not asset:
        raise FundingServiceError("line asset not found", code="not_found")
    link = db.get(models.ItemProjectLineAsset, (project_id, line_asset_id))
    if link:
        return asset
    db.add(models.ItemProjectLineAsset(item_project_id=project_id, line_asset_id=line_asset_id))
    db.commit()
    return asset


def remove_line_asset_from_item_project(db: Session, project_id: int, line_asset_id: int) -> None:
    link = db.get(models.ItemProjectLineAsset, (project_id, line_asset_id))
    if not link:
        raise FundingServiceError("line asset link not found", code="not_found")
    db.delete(link)
    db.commit()


# ---------------------------------------------------------------------------
# Budget tree
# ---------------------------------------------------------------------------


def _project_asset_map(db: Session, project_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    mapping: Dict[int, List[Dict[str, Any]]] = {}
    if not project_ids:
        return mapping
    rows = db.execute(
        select(
            models.ItemProjectLineAsset.item_project_id,
            models.LineAsset.id,
            models.LineAsset.name,
        )
        .join(models.LineAsset, models.LineAsset.id == models.ItemProjectLineAsset.line_asset_id)
        .where(models.ItemProjectLineAsset.item_project_id.in_(project_ids))
        .order_by(models.LineAsset.name.asc())
    )
    for project_id, asset_id, name in rows:
        mapping.setdefault(project_id, []).append({"id": asset_id, "name": name})
    return mapping


def _project_rollups(db: Session, project_ids: List[int]) -> Dict[int, float]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(
            models.Category.item_project_id,
            func.coalesce(func.sum(models.Category.amount_leaf), 0.0),
        )
        .where(models.Category.item_project_id.in_(project_ids), models.Category.is_leaf.is_(True))
        .group_by(models.Category.item_project_id)
    )
    return {pid: float(amount or 0) for pid, amount in rows}


def budget_tree(
    db: Session,
    budget_id: int,
    *,
    project_id: Optional[int],
    include: IncludeSet,
) -> List[Dict[str, Any]]:
    budget = db.get(models_finance.FundingSource, budget_id)
    if not budget:
        raise FundingServiceError("budget not found", code="not_found")

    projects = db.execute(
        select(models.Project)
        .where(models.Project.budget_id == budget_id)
        .order_by(models.Project.name.asc())
    ).scalars().all()
    if project_id is not None:
        projects = [p for p in projects if p.id == project_id]
    project_ids = [p.id for p in projects]

    categories = db.execute(
        select(models.Category)
        .where(models.Category.budget_id == budget_id)
        .order_by(models.Category.path_depth.asc(), models.Category.name.asc())
    ).scalars().all()
    if project_id is not None:
        categories = [c for c in categories if c.project_id == project_id]

    rollups = _project_rollups(db, project_ids)
    asset_map = _project_asset_map(db, project_ids) if "assets" in include else {}

    nodes: List[Dict[str, Any]] = []

    budget_node: Dict[str, Any] = {
        "id": budget.id,
        "type": "budget",
        "name": budget.name,
        "depth": 0,
        "is_leaf": False,
        "amount_leaf": None,
        "rollup_amount": _float(budget.budget_amount_cache),
        "project_id": None,
        "budget_id": budget.id,
        "parent_id": None,
    }
    if "paths" in include:
        budget_node["path_ids"] = [budget.id]
        budget_node["path_names"] = [budget.name]
    if "tags" in include:
        budget_node["tags"] = _tag_bundle(db, "budget", budget.id)
    nodes.append(budget_node)

    for project in projects:
        proj_node: Dict[str, Any] = {
            "id": project.id,
            "type": "project",
            "name": project.name,
            "depth": 1,
            "is_leaf": False,
            "amount_leaf": None,
            "rollup_amount": rollups.get(project.id, 0.0),
            "project_id": project.id,
            "budget_id": project.budget_id,
            "parent_id": budget.id,
        }
        if "paths" in include:
            proj_node["path_ids"] = [budget.id, project.id]
            proj_node["path_names"] = [budget.name, project.name]
        if "tags" in include:
            proj_node["tags"] = _tag_bundle(db, "item_project", project.id)
        if "assets" in include:
            assets = asset_map.get(project.id, [])
            proj_node["assets"] = {"count": len(assets), "items": assets}
        nodes.append(proj_node)

    for category in categories:
        depth = 2 + (category.path_depth or 0)
        node: Dict[str, Any] = {
            "id": category.id,
            "type": "category",
            "name": category.name,
            "depth": depth,
            "is_leaf": category.is_leaf,
            "amount_leaf": _float(category.amount_leaf),
            "rollup_amount": _float(category.rollup_amount),
            "project_id": category.project_id,
            "budget_id": category.budget_id,
            "parent_id": category.parent_id,
        }
        if "paths" in include:
            node["path_ids"] = category.path_ids
            node["path_names"] = category.path_names
        if "tags" in include:
            node["tags"] = _tag_bundle(db, "category", category.id)
        if "assets" in include and category.is_leaf:
            assets = asset_map.get(category.project_id, [])
            node["assets"] = {"count": len(assets), "items": assets}
        nodes.append(node)

    return nodes
