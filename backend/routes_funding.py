"""API routes for funding sources, projects, categories, and related resources."""

from __future__ import annotations

import json
from typing import Iterable, List, Optional, Set, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .db import get_db
from .services import funding, tags as tag_service
from . import models, schemas

router = APIRouter(prefix="/api")

_ERROR_STATUS_MAP = {
    "not_found": 404,
    "allocations_present": 409,
    "categories_present": 409,
    "missing_leaf_amounts": 409,
    "assets_present": 409,
    "parent_scope_mismatch": 409,
    "parent_not_found": 404,
    "invalid_parent": 422,
    "has_children": 422,
}


def _parse_include(value: Optional[str]) -> Set[str]:
    if not value:
        return set()
    parts: Iterable[str]
    if isinstance(value, list):  # pragma: no cover - interface guard
        parts = value
    else:
        parts = [value]
    include: Set[str] = set()
    for part in parts:
        for item in part.split(","):
            item = item.strip()
            if item:
                include.add(item)
    return include


def _dt(value):
    return value.isoformat() if value else None


def _date(value):
    return value.isoformat() if value else None


def _arr(value: Optional[Union[str, List]]) -> Optional[List]:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [text]
    return list(value)


def _tag_bundle_schema(bundle: Optional[dict]) -> Optional[schemas.TagBundleOut]:
    if not bundle:
        return None
    return schemas.TagBundleOut(
        direct=[schemas.TagRef(**ref) for ref in bundle.get("direct", [])],
        inherited=[schemas.TagRef(**ref) for ref in bundle.get("inherited", [])],
        effective=[schemas.TagRef(**ref) for ref in bundle.get("effective", [])],
    )


def _asset_list_schema(asset_data: Optional[dict]) -> Optional[schemas.AssetListOut]:
    if not asset_data:
        return None
    items = [schemas.LineAssetSummary(**item) for item in asset_data.get("items", [])]
    return schemas.AssetListOut(count=asset_data.get("count", len(items)), items=items)


def _budget_to_schema(data: dict) -> schemas.BudgetOut:
    stats = data.get("stats")
    tags = _tag_bundle_schema(data.get("tags"))
    stats_schema = schemas.BudgetStatsOut(**stats) if stats else None
    return schemas.BudgetOut(
        id=data["id"],
        name=data["name"],
        owner=data.get("owner"),
        is_cost_center=data["is_cost_center"],
        closure_date=_date(data.get("closure_date")),
        description=data.get("description"),
        budget_amount_cache=data.get("budget_amount_cache"),
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("updated_at")),
        stats=stats_schema,
        tags=tags,
    )


def _item_project_to_schema(data: dict) -> schemas.ItemProjectOut:
    return schemas.ItemProjectOut(
        id=data["id"],
        name=data["name"],
        budget_id=data["budget_id"],
        description=data.get("description"),
        legacy_portfolio_id=data.get("legacy_portfolio_id"),
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("updated_at")),
        rollup_amount=data.get("rollup_amount", 0.0),
        tags=_tag_bundle_schema(data.get("tags")),
        assets=_asset_list_schema(data.get("assets")),
    )


def _category_to_schema(data: dict) -> schemas.CategoryOut:
    return schemas.CategoryOut(
        id=data["id"],
        name=data["name"],
        parent_id=data.get("parent_id"),
        project_id=data["project_id"],
        budget_id=data["budget_id"],
        is_leaf=data["is_leaf"],
        amount_leaf=data.get("amount_leaf"),
        rollup_amount=data.get("rollup_amount"),
        path_depth=data.get("path_depth"),
        path_ids=_arr(data.get("path_ids")),
        path_names=_arr(data.get("path_names")),
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("updated_at")),
        tags=_tag_bundle_schema(data.get("tags")),
    )


def _tree_node_to_schema(data: dict) -> schemas.FundingTreeNode:
    return schemas.FundingTreeNode(
        id=data["id"],
        type=data["type"],
        name=data["name"],
        depth=data["depth"],
        is_leaf=data["is_leaf"],
        amount_leaf=data.get("amount_leaf"),
        rollup_amount=data.get("rollup_amount"),
        project_id=data.get("project_id"),
        budget_id=data.get("budget_id"),
        parent_id=data.get("parent_id"),
        path_ids=_arr(data.get("path_ids")),
        path_names=_arr(data.get("path_names")),
        tags=_tag_bundle_schema(data.get("tags")),
        assets=_asset_list_schema(data.get("assets")),
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("updated_at")),
    )


def _line_asset_to_schema(data: dict) -> schemas.LineAssetOut:
    return schemas.LineAssetOut(
        id=data["id"],
        name=data["name"],
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("updated_at")),
    )


def _job_to_schema(job: models.BackgroundJob) -> schemas.BackgroundJobOut:
    return schemas.BackgroundJobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        payload=job.payload,
        started_at=_dt(job.started_at),
        finished_at=_dt(job.finished_at),
        error=job.error,
        created_at=_dt(job.created_at),
        updated_at=_dt(job.updated_at),
    )


def _raise_service_error(exc: funding.FundingServiceError) -> None:
    status = _ERROR_STATUS_MAP.get(exc.code, 400)
    raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/budgets", response_model=List[schemas.BudgetOut])
def api_list_budgets(
    q: Optional[str] = Query(default=None),
    is_cost_center: Optional[bool] = Query(default=None),
    owner: Optional[str] = Query(default=None),
    ids: Optional[List[int]] = Query(default=None),
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        records = funding.list_budgets(
            db,
            q=q,
            is_cost_center=is_cost_center,
            owner=owner,
            ids=ids,
            include=include_set,
        )
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return [_budget_to_schema(record) for record in records]


@router.get("/budgets/{budget_id}", response_model=schemas.BudgetOut)
def api_get_budget(
    budget_id: int,
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        record = funding.get_budget(db, budget_id, include=include_set)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return _budget_to_schema(record)


@router.post("/budgets", response_model=schemas.BudgetOut, status_code=201)
def api_create_budget(payload: schemas.BudgetCreate, db: Session = Depends(get_db)):
    budget = funding.create_budget(
        db,
        name=payload.name,
        owner=payload.owner,
        is_cost_center=payload.is_cost_center,
        closure_date=payload.closure_date,
        description=payload.description,
    )
    record = funding.get_budget(db, budget.id, include=set())
    return _budget_to_schema(record)


@router.patch("/budgets/{budget_id}", response_model=schemas.BudgetOut)
def api_update_budget(
    budget_id: int,
    payload: schemas.BudgetUpdate,
    db: Session = Depends(get_db),
):
    try:
        funding.update_budget(
            db,
            budget_id,
            name=payload.name,
            owner=payload.owner,
            is_cost_center=payload.is_cost_center,
            closure_date=payload.closure_date,
            description=payload.description,
        )
        record = funding.get_budget(db, budget_id, include=set())
        return _budget_to_schema(record)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)


@router.delete("/budgets/{budget_id}")
def api_delete_budget(budget_id: int, db: Session = Depends(get_db)):
    try:
        funding.delete_budget(db, budget_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return {"ok": True}


@router.get("/item-projects", response_model=List[schemas.ItemProjectOut])
def api_list_item_projects(
    budget_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None),
    ids: Optional[List[int]] = Query(default=None),
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        records = funding.list_item_projects(
            db,
            budget_id=budget_id,
            q=q,
            ids=ids,
            include=include_set,
        )
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return [_item_project_to_schema(record) for record in records]


@router.get("/item-projects/{project_id}", response_model=schemas.ItemProjectOut)
def api_get_item_project(
    project_id: int,
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        record = funding.get_item_project(db, project_id, include=include_set)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return _item_project_to_schema(record)


@router.post("/item-projects", response_model=schemas.ItemProjectOut, status_code=201)
def api_create_item_project(payload: schemas.ItemProjectCreate, db: Session = Depends(get_db)):
    project = funding.create_item_project(
        db,
        budget_id=payload.budget_id,
        name=payload.name,
        description=payload.description,
    )
    record = funding.get_item_project(db, project.id, include=set())
    return _item_project_to_schema(record)


@router.patch("/item-projects/{project_id}", response_model=schemas.ItemProjectOut)
def api_update_item_project(
    project_id: int,
    payload: schemas.ItemProjectUpdate,
    db: Session = Depends(get_db),
):
    try:
        project = funding.update_item_project(
            db,
            project_id,
            name=payload.name,
            description=payload.description,
        )
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    record = funding.get_item_project(db, project.id, include=set())
    return _item_project_to_schema(record)


@router.delete("/item-projects/{project_id}")
def api_delete_item_project(project_id: int, db: Session = Depends(get_db)):
    try:
        funding.delete_item_project(db, project_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return {"ok": True}


@router.post(
    "/item-projects/{project_id}/line-assets",
    response_model=schemas.LineAssetOut,
    status_code=201,
)
def api_attach_line_asset(
    project_id: int,
    payload: schemas.ItemProjectAssetLink,
    db: Session = Depends(get_db),
):
    try:
        asset = funding.add_line_asset_to_item_project(db, project_id, payload.line_asset_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return _line_asset_to_schema(
        {
            "id": asset.id,
            "name": asset.name,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }
    )


@router.delete("/item-projects/{project_id}/line-assets/{line_asset_id}")
def api_detach_line_asset(project_id: int, line_asset_id: int, db: Session = Depends(get_db)):
    try:
        funding.remove_line_asset_from_item_project(db, project_id, line_asset_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return {"ok": True}


@router.get("/categories", response_model=List[schemas.CategoryOut])
def api_list_categories(
    budget_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    parent_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None),
    ids: Optional[List[int]] = Query(default=None),
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        records = funding.list_categories(
            db,
            budget_id=budget_id,
            project_id=project_id,
            parent_id=parent_id,
            q=q,
            ids=ids,
            include=include_set,
        )
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return [_category_to_schema(record) for record in records]


@router.get("/categories/{category_id}", response_model=schemas.CategoryOut)
def api_get_category(
    category_id: int,
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        record = funding.get_category(db, category_id, include=include_set)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return _category_to_schema(record)


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def api_create_category(payload: schemas.CategoryCreate, db: Session = Depends(get_db)):
    try:
        category = funding.create_category(
            db,
            name=payload.name,
            project_id=payload.project_id,
            budget_id=payload.budget_id,
            parent_id=payload.parent_id,
            is_leaf=payload.is_leaf,
            amount_leaf=payload.amount_leaf,
            description=payload.description,
        )
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    record = funding.get_category(db, category.id, include=set())
    return _category_to_schema(record)


@router.patch("/categories/{category_id}", response_model=schemas.CategoryOut)
def api_update_category(
    category_id: int,
    payload: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
):
    try:
        updates = payload.model_dump(exclude_unset=True)
        category = funding.update_category(db, category_id, **updates)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    record = funding.get_category(db, category.id, include=set())
    return _category_to_schema(record)


@router.delete("/categories/{category_id}")
def api_delete_category(category_id: int, db: Session = Depends(get_db)):
    try:
        funding.delete_category(db, category_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return {"ok": True}


@router.get("/categories/{category_id}/can-move", response_model=schemas.CategoryMoveCheckResponse)
def api_can_move_category(
    category_id: int,
    new_parent_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        result = funding.can_move_category(db, category_id, new_parent_id=new_parent_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return schemas.CategoryMoveCheckResponse(**result)


@router.get("/budgets/{budget_id}/tree", response_model=List[schemas.FundingTreeNode])
def api_budget_tree(
    budget_id: int,
    project_id: Optional[int] = Query(default=None),
    include: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    include_set = _parse_include(include)
    try:
        nodes = funding.budget_tree(db, budget_id, project_id=project_id, include=include_set)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return [_tree_node_to_schema(node) for node in nodes]


@router.get("/line-assets", response_model=List[schemas.LineAssetOut])
def api_list_line_assets(
    category_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None),
    ids: Optional[List[int]] = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        assets = funding.list_line_assets(
            db,
            category_id=category_id,
            project_id=project_id,
            q=q,
            ids=ids,
        )
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return [_line_asset_to_schema(asset) for asset in assets]


@router.post("/line-assets", response_model=schemas.LineAssetOut, status_code=201)
def api_create_line_asset(payload: schemas.LineAssetCreate, db: Session = Depends(get_db)):
    asset = funding.create_line_asset(db, name=payload.name)
    return _line_asset_to_schema({
        "id": asset.id,
        "name": asset.name,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    })


@router.patch("/line-assets/{line_asset_id}", response_model=schemas.LineAssetOut)
def api_update_line_asset(line_asset_id: int, payload: schemas.LineAssetUpdate, db: Session = Depends(get_db)):
    try:
        asset = funding.update_line_asset(db, line_asset_id, name=payload.name)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return _line_asset_to_schema({
        "id": asset.id,
        "name": asset.name,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    })


@router.delete("/line-assets/{line_asset_id}")
def api_delete_line_asset(line_asset_id: int, db: Session = Depends(get_db)):
    try:
        funding.delete_line_asset(db, line_asset_id)
    except funding.FundingServiceError as exc:
        _raise_service_error(exc)
    return {"ok": True}


@router.get("/tags/usage", response_model=List[schemas.TagUsageOut])
def api_tag_usage(db: Session = Depends(get_db)):
    usages = tag_service.get_usage(db)
    results: List[schemas.TagUsageOut] = []
    for item in usages:
        tag_data = item["tag"]
        tag_schema = schemas.TagOut(
            id=tag_data["id"],
            name=tag_data["name"],
            color=tag_data.get("color"),
            description=tag_data.get("description"),
            is_deprecated=tag_data.get("is_deprecated", False),
            created_at=tag_data.get("created_at"),
            updated_at=tag_data.get("updated_at"),
        )
        results.append(schemas.TagUsageOut(tag=tag_schema, assignments=item["assignments"]))
    return results


@router.post("/admin/rebuild-effective-tags", response_model=schemas.BackgroundJobOut)
def api_rebuild_effective_tags(
    only_for: Optional[str] = Query(default=None),
    payload: schemas.RebuildRequest = Body(default=schemas.RebuildRequest()),
    db: Session = Depends(get_db),
):
    job = tag_service.rebuild_effective_tags(db, actor=payload.actor, only_for=only_for)
    return _job_to_schema(job)
