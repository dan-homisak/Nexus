from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session, selectinload

from .db import get_db
from . import models_finance
from .schemas_finance import (
    DeliverableTemplateApplyRequest,
    DeliverableLotOut,
    FxRateIn,
    FxRateOut,
    FxRateUpdateIn,
    FundingSourceIn,
    FundingSourceOut,
    InvoiceIn,
    InvoiceOut,
    LotCreateIn,
    MilestoneUpdateIn,
    PaymentScheduleGenerateV2Request,
    PaymentScheduleGenerateRequest,
    PaymentScheduleIn,
    PaymentScheduleOut,
    PaymentScheduleUpdateIn,
    PurchaseOrderIn,
    PurchaseOrderOut,
    ReallocateRequest,
    ReportDefinitionIn,
    ReportDefinitionOut,
    ReportRunIn,
    SavedReportResult,
    CheckpointTypeOut,
)
from .schemas_finance import MilestoneOut
from .sql.views import apply_views

router = APIRouter(prefix="/api", tags=["finance"])


def _emit_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: Any,
    event_type: str,
    by: str = "system",
    payload: Optional[dict[str, Any]] = None,
) -> None:
    event = models_finance.Event(
        entity_type=entity_type,
        entity_id=str(entity_id),
        event_type=event_type,
        by=by,
        payload_json=payload or {},
        at=dt.datetime.utcnow(),
    )
    session.add(event)
    session.flush()


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal("0")


def _resolve_group_fields(group_by: Optional[str], mapping: dict[str, str], default: list[str]) -> list[str]:
    if not group_by:
        return list(default)
    fields: list[str] = []
    for token in group_by.split(","):
        token = token.strip()
        if not token:
            continue
        key = mapping.get(token, mapping.get(token.lower()))
        if key and key not in fields:
            fields.append(key)
    return fields or list(default)


def _aggregate_numeric(
    rows: Iterable[dict[str, Any]],
    *,
    group_fields: list[str],
    numeric_mapping: dict[str, str],
) -> list[dict[str, Any]]:
    aggregated: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for row in rows:
        key = tuple(row.get(field) for field in group_fields)
        if key not in aggregated:
            aggregated[key] = {field: row.get(field) for field in group_fields}
            for metric in numeric_mapping:
                aggregated[key][metric] = Decimal("0")
            order.append(key)
        bucket = aggregated[key]
        for metric, column in numeric_mapping.items():
            bucket[metric] += _to_decimal(row.get(column))
    return [aggregated[k] for k in order]


def _paginate(data: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    start = max(offset, 0)
    end = start + max(limit, 1)
    return data[start:end]


def _finalise_numeric(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, Decimal):
            result[key] = float(value)
        else:
            result[key] = value
    return result


def _fetch_view_rows(
    db: Session,
    *,
    view_name: str,
    where_clauses: list[str],
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    apply_views(db.bind)
    sql = f"SELECT * FROM {view_name}"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    rows = db.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def _parse_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _jsonify(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dt.date):
            result[key] = value.isoformat()
        elif isinstance(value, Decimal):
            result[key] = float(value)
        else:
            result[key] = value
    return result


def _document_total_amount(invoice: Optional[models_finance.Invoice], purchase_order: Optional[models_finance.PurchaseOrder]) -> Decimal:
    if invoice and invoice.total_amount is not None:
        return _to_decimal(invoice.total_amount)
    if purchase_order and purchase_order.total_amount is not None:
        return _to_decimal(purchase_order.total_amount)
    return Decimal("0")


def _document_base_date(invoice: Optional[models_finance.Invoice], purchase_order: Optional[models_finance.PurchaseOrder]) -> dt.date:
    if invoice and invoice.invoice_date:
        return invoice.invoice_date
    if purchase_order and purchase_order.ordered_date:
        return purchase_order.ordered_date
    return dt.date.today()


def _generate_payment_schedule_records(
    db: Session,
    payload: PaymentScheduleGenerateV2Request,
) -> list[models_finance.PaymentSchedule]:
    if payload.invoice_id and payload.po_id:
        raise HTTPException(status_code=400, detail="Provide either invoice_id or po_id, not both")

    invoice = db.get(models_finance.Invoice, payload.invoice_id) if payload.invoice_id else None
    purchase_order = db.get(models_finance.PurchaseOrder, payload.po_id) if payload.po_id else None
    if not invoice and not purchase_order:
        raise HTTPException(status_code=404, detail="Source document not found")

    total_amount = _document_total_amount(invoice, purchase_order)
    base_date = _document_base_date(invoice, purchase_order)
    rule = payload.rule or "NET_N"
    splits = payload.splits or []
    doc_kwargs = {"invoice": invoice, "purchase_order": purchase_order}

    created: list[models_finance.PaymentSchedule] = []

    if rule != "CUSTOM" and not splits:
        net_days = payload.net_days if rule != "NET_0" else 0
        due_date = base_date + dt.timedelta(days=net_days) if net_days else base_date
        schedule = models_finance.PaymentSchedule(
            **doc_kwargs,
            percent=Decimal("1") if total_amount else None,
            amount=total_amount if total_amount else None,
            due_date_rule=rule,
            net_days=net_days,
            due_date=due_date,
            status="PLANNED",
        )
        db.add(schedule)
        db.flush()
        _emit_event(
            db,
            entity_type="payment_schedule",
            entity_id=schedule.id,
            event_type="payment_schedule_generated",
            by=payload.by,
            payload={"rule": rule, "net_days": net_days},
        )
        created.append(schedule)
        return created

    if not splits:
        raise HTTPException(status_code=400, detail="splits required for CUSTOM generation")

    for idx, split in enumerate(splits):
        percent_value = split.percent
        amount_value = split.amount
        if percent_value is None and amount_value is None:
            raise HTTPException(status_code=400, detail="Each split requires percent or amount")

        if amount_value is not None:
            amount_value = _to_decimal(amount_value)
        if percent_value is not None:
            percent_value = _to_decimal(percent_value)

        if percent_value is None and amount_value is not None and total_amount:
            percent_value = amount_value / total_amount
        if amount_value is None and percent_value is not None and total_amount:
            amount_value = total_amount * percent_value

        due_date = split.due_date or (
            base_date + dt.timedelta(days=payload.net_days or 0)
            if payload.net_days is not None
            else base_date
        )

        schedule = models_finance.PaymentSchedule(
            **doc_kwargs,
            percent=percent_value,
            amount=amount_value,
            due_date_rule=rule,
            net_days=payload.net_days,
            due_date=due_date,
            status="PLANNED",
        )
        db.add(schedule)
        db.flush()
        _emit_event(
            db,
            entity_type="payment_schedule",
            entity_id=schedule.id,
            event_type="payment_schedule_generated",
            by=payload.by,
            payload={
                "rule": rule,
                "split_index": idx,
                "percent": float(percent_value) if percent_value is not None else None,
                "amount": float(amount_value) if amount_value is not None else None,
            },
        )
        created.append(schedule)

    return created


def _serialize_lot(lot: models_finance.FulfillmentLot) -> DeliverableLotOut:
    purchase_order = lot.po_line.purchase_order if lot.po_line else None
    milestones = [MilestoneOut.model_validate(m) for m in lot.milestones]
    is_late = any(
        m.planned_date and not m.actual_date and m.planned_date < dt.date.today()
        for m in lot.milestones
    )
    return DeliverableLotOut(
        id=lot.id,
        po_line_id=lot.po_line_id,
        purchase_order_id=purchase_order.id if purchase_order else None,
        po_number=purchase_order.po_number if purchase_order else None,
        lot_qty=lot.lot_qty,
        lot_identifier=lot.lot_identifier,
        notes=lot.notes,
        is_late=is_late,
        milestones=milestones,
    )


@router.get("/funding-sources", response_model=list[FundingSourceOut])
def list_funding_sources(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.FundingSource)).scalars().all()


@router.post("/funding-sources", response_model=FundingSourceOut)
def create_funding_source(payload: FundingSourceIn, db: Session = Depends(get_db)):
    fs = models_finance.FundingSource(**payload.model_dump())
    db.add(fs)
    db.commit()
    db.refresh(fs)
    return fs


@router.put("/funding-sources/{fs_id}", response_model=FundingSourceOut)
def update_funding_source(fs_id: int, payload: FundingSourceIn, db: Session = Depends(get_db)):
    fs = db.get(models_finance.FundingSource, fs_id)
    if not fs:
        raise HTTPException(status_code=404, detail="Funding source not found")
    for key, value in payload.model_dump().items():
        setattr(fs, key, value)
    db.commit()
    db.refresh(fs)
    return fs


@router.delete("/funding-sources/{fs_id}")
def delete_funding_source(fs_id: int, db: Session = Depends(get_db)):
    fs = db.get(models_finance.FundingSource, fs_id)
    if not fs:
        return {"ok": True}
    db.delete(fs)
    db.commit()
    return {"ok": True}


@router.get("/views/budget-commit-actual")
def get_budget_commit_actual(
    funding_source_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    category_id: Optional[int] = Query(default=None),
    date_from: Optional[dt.date] = Query(default=None),
    date_to: Optional[dt.date] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if funding_source_id is not None:
        where_clauses.append("funding_source_id = :funding_source_id")
        params["funding_source_id"] = funding_source_id
    if project_id is not None:
        where_clauses.append("project_id = :project_id")
        params["project_id"] = project_id
    if category_id is not None:
        where_clauses.append("category_id = :category_id")
        params["category_id"] = category_id

    rows = _fetch_view_rows(
        db,
        view_name="v_budget_commit_actual",
        where_clauses=where_clauses,
        params=params,
    )

    group_mapping = {
        "funding_source": "funding_source_id",
        "funding_source_id": "funding_source_id",
        "project": "project_id",
        "project_id": "project_id",
        "category": "category_id",
        "category_id": "category_id",
        "currency": "currency",
    }
    group_fields = _resolve_group_fields(
        group_by,
        mapping=group_mapping,
        default=["funding_source_id", "project_id", "category_id", "currency"],
    )

    numeric_mapping = {
        "budget_usd": "forecast_amount_usd",
        "commitment_usd": "commitment_amount_usd",
        "accrual_usd": "accrual_amount_usd",
        "cash_usd": "cash_amount_usd",
    }
    aggregated = _aggregate_numeric(rows, group_fields=group_fields, numeric_mapping=numeric_mapping)

    results: list[dict[str, Any]] = []
    for record in aggregated:
        budget_val = record.get("budget_usd", Decimal("0"))
        commitment_val = record.get("commitment_usd", Decimal("0"))
        accrual_val = record.get("accrual_usd", Decimal("0"))
        cash_val = record.get("cash_usd", Decimal("0"))
        open_commitment = max(commitment_val - (accrual_val + cash_val), Decimal("0"))
        variance = (accrual_val + cash_val) - budget_val
        record["open_commitment_usd"] = open_commitment
        record["variance_usd"] = variance
        record["variance_pct"] = float(variance / budget_val * 100) if budget_val else None
        results.append(_finalise_numeric(record))

    return _paginate(results, limit=limit, offset=offset)


@router.get("/views/open-commitments")
def get_open_commitments(
    funding_source_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    vendor_id: Optional[int] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if funding_source_id is not None:
        where_clauses.append("funding_source_id = :funding_source_id")
        params["funding_source_id"] = funding_source_id
    if project_id is not None:
        where_clauses.append("project_id = :project_id")
        params["project_id"] = project_id
    if vendor_id is not None:
        where_clauses.append("vendor_id = :vendor_id")
        params["vendor_id"] = vendor_id

    rows = _fetch_view_rows(
        db,
        view_name="v_open_commitments",
        where_clauses=where_clauses,
        params=params,
    )

    for row in rows:
        total_amount = _to_decimal(row.get("total_amount"))
        amount_usd = _to_decimal(row.get("amount_usd"))
        fx_ratio = Decimal("1")
        if total_amount:
            fx_ratio = amount_usd / total_amount if amount_usd else Decimal("1")
        row["budget_usd_calc"] = amount_usd
        row["commitment_usd_calc"] = _to_decimal(row.get("line_amount")) * fx_ratio
        row["open_commitment_usd_calc"] = _to_decimal(row.get("open_amount")) * fx_ratio

    group_mapping = {
        "funding_source": "funding_source_id",
        "funding_source_id": "funding_source_id",
        "project": "project_id",
        "project_id": "project_id",
        "vendor": "vendor_id",
        "vendor_id": "vendor_id",
        "purchase_order": "purchase_order_id",
        "po": "purchase_order_id",
        "po_number": "po_number",
    }
    group_fields = _resolve_group_fields(
        group_by,
        mapping=group_mapping,
        default=["funding_source_id", "purchase_order_id", "vendor_id"],
    )

    numeric_mapping = {
        "budget_usd": "budget_usd_calc",
        "commitment_usd": "commitment_usd_calc",
        "open_commitment_usd": "open_commitment_usd_calc",
    }
    aggregated = _aggregate_numeric(rows, group_fields=group_fields, numeric_mapping=numeric_mapping)

    results: list[dict[str, Any]] = []
    for record in aggregated:
        record.setdefault("accrual_usd", Decimal("0"))
        record.setdefault("cash_usd", Decimal("0"))
        record.setdefault("variance_usd", Decimal("0"))
        record.setdefault("variance_pct", None)
        results.append(_finalise_numeric(record))

    return _paginate(results, limit=limit, offset=offset)


@router.get("/views/vendor-spend-aging")
def get_vendor_spend_aging(
    vendor_id: Optional[int] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if vendor_id is not None:
        where_clauses.append("vendor_id = :vendor_id")
        params["vendor_id"] = vendor_id

    rows = _fetch_view_rows(
        db,
        view_name="v_vendor_spend_aging",
        where_clauses=where_clauses,
        params=params,
    )

    group_mapping = {
        "vendor": "vendor_id",
        "vendor_id": "vendor_id",
        "currency": "currency",
    }
    group_fields = _resolve_group_fields(
        group_by,
        mapping=group_mapping,
        default=["vendor_id", "currency"],
    )

    numeric_mapping = {
        "bucket_0_30": "bucket_0_30",
        "bucket_31_60": "bucket_31_60",
        "bucket_61_90": "bucket_61_90",
        "bucket_90_plus": "bucket_90_plus",
    }
    aggregated = _aggregate_numeric(rows, group_fields=group_fields, numeric_mapping=numeric_mapping)

    results: list[dict[str, Any]] = []
    for record in aggregated:
        record.setdefault("budget_usd", Decimal("0"))
        record.setdefault("commitment_usd", Decimal("0"))
        record.setdefault("accrual_usd", Decimal("0"))
        record.setdefault("cash_usd", Decimal("0"))
        record.setdefault("open_commitment_usd", Decimal("0"))
        record.setdefault("variance_usd", Decimal("0"))
        record.setdefault("variance_pct", None)
        results.append(_finalise_numeric(record))

    return _paginate(results, limit=limit, offset=offset)


@router.get("/views/open-items")
def get_open_items(
    funding_source_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    vendor_id: Optional[int] = Query(default=None),
    date_from: Optional[dt.date] = Query(default=None),
    date_to: Optional[dt.date] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if funding_source_id is not None:
        where_clauses.append("funding_source_id = :funding_source_id")
        params["funding_source_id"] = funding_source_id
    if project_id is not None:
        where_clauses.append("project_id = :project_id")
        params["project_id"] = project_id
    if vendor_id is not None:
        where_clauses.append("vendor_id = :vendor_id")
        params["vendor_id"] = vendor_id

    rows = _fetch_view_rows(
        db,
        view_name="v_open_items",
        where_clauses=where_clauses,
        params=params,
    )

    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        planned_date = _parse_date(row.get("planned_date"))
        actual_date = _parse_date(row.get("actual_date"))
        include = True
        if date_from and planned_date and planned_date < date_from:
            include = False
        if date_to and planned_date and planned_date > date_to:
            include = False
        if include:
            row["planned_date"] = planned_date.isoformat() if planned_date else None
            row["actual_date"] = actual_date.isoformat() if actual_date else None
            row["is_late"] = bool(row.get("is_late"))
            filtered_rows.append(row)

    group_mapping = {
        "funding_source": "funding_source_id",
        "funding_source_id": "funding_source_id",
        "project": "project_id",
        "project_id": "project_id",
        "vendor": "vendor_id",
        "vendor_id": "vendor_id",
        "purchase_order": "purchase_order_id",
        "milestone": "milestone_instance_id",
        "status": "status",
        "planned_date": "planned_date",
        "actual_date": "actual_date",
        "is_late": "is_late",
    }
    group_fields = _resolve_group_fields(
        group_by,
        mapping=group_mapping,
        default=["purchase_order_id", "milestone_instance_id", "status", "planned_date", "actual_date", "is_late"],
    )

    numeric_mapping: dict[str, str] = {}
    aggregated = _aggregate_numeric(filtered_rows, group_fields=group_fields, numeric_mapping=numeric_mapping)

    results: list[dict[str, Any]] = []
    for record in aggregated:
        record.setdefault("budget_usd", Decimal("0"))
        record.setdefault("commitment_usd", Decimal("0"))
        record.setdefault("accrual_usd", Decimal("0"))
        record.setdefault("cash_usd", Decimal("0"))
        record.setdefault("open_commitment_usd", Decimal("0"))
        record.setdefault("variance_usd", Decimal("0"))
        record.setdefault("variance_pct", None)
        results.append(_finalise_numeric(record))

    return _paginate(results, limit=limit, offset=offset)


@router.get("/views/future-plan")
def get_future_plan(
    funding_source_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    category_id: Optional[int] = Query(default=None),
    date_from: Optional[dt.date] = Query(default=None),
    date_to: Optional[dt.date] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if funding_source_id is not None:
        where_clauses.append("funding_source_id = :funding_source_id")
        params["funding_source_id"] = funding_source_id
    if project_id is not None:
        where_clauses.append("project_id = :project_id")
        params["project_id"] = project_id
    if category_id is not None:
        where_clauses.append("category_id = :category_id")
        params["category_id"] = category_id

    rows = _fetch_view_rows(
        db,
        view_name="v_future_plan",
        where_clauses=where_clauses,
        params=params,
    )

    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        txn_date = _parse_date(row.get("txn_date"))
        if date_from and txn_date and txn_date < date_from:
            continue
        if date_to and txn_date and txn_date > date_to:
            continue
        amount_usd = _to_decimal(row.get("amount_usd"))
        state = row.get("state") or "FORECAST"
        row["txn_date"] = txn_date.isoformat() if txn_date else None
        row["txn_month"] = txn_date.strftime("%Y-%m") if txn_date else None
        row["budget_usd_calc"] = amount_usd if state == "FORECAST" else Decimal("0")
        row["commitment_usd_calc"] = amount_usd if state == "COMMITMENT" else Decimal("0")
        filtered_rows.append(row)

    group_mapping = {
        "funding_source": "funding_source_id",
        "funding_source_id": "funding_source_id",
        "project": "project_id",
        "project_id": "project_id",
        "category": "category_id",
        "category_id": "category_id",
        "state": "state",
        "month": "txn_month",
    }
    group_fields = _resolve_group_fields(
        group_by,
        mapping=group_mapping,
        default=["funding_source_id", "project_id", "category_id", "state"],
    )

    numeric_mapping = {
        "budget_usd": "budget_usd_calc",
        "commitment_usd": "commitment_usd_calc",
    }
    aggregated = _aggregate_numeric(filtered_rows, group_fields=group_fields, numeric_mapping=numeric_mapping)

    results: list[dict[str, Any]] = []
    for record in aggregated:
        record.setdefault("accrual_usd", Decimal("0"))
        record.setdefault("cash_usd", Decimal("0"))
        record.setdefault("open_commitment_usd", Decimal("0"))
        variance = record.get("commitment_usd", Decimal("0")) - record.get("budget_usd", Decimal("0"))
        record["variance_usd"] = variance
        budget_val = record.get("budget_usd", Decimal("0"))
        record["variance_pct"] = float(variance / budget_val * 100) if budget_val else None
        results.append(_finalise_numeric(record))

    return _paginate(results, limit=limit, offset=offset)


@router.get("/views/to-car-closure")
def get_to_car_closure(
    funding_source_id: Optional[int] = Query(default=None),
    group_by: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    where_clauses: list[str] = []
    params: dict[str, Any] = {}
    if funding_source_id is not None:
        where_clauses.append("funding_source_id = :funding_source_id")
        params["funding_source_id"] = funding_source_id

    rows = _fetch_view_rows(
        db,
        view_name="v_to_car_closure",
        where_clauses=where_clauses,
        params=params,
    )

    group_mapping = {
        "funding_source": "funding_source_id",
        "funding_source_id": "funding_source_id",
        "temporary": "is_temporary",
        "is_temporary": "is_temporary",
        "closure_date": "closure_date",
    }
    group_fields = _resolve_group_fields(
        group_by,
        mapping=group_mapping,
        default=["funding_source_id", "closure_date", "is_temporary"],
    )

    numeric_mapping = {
        "budget_usd": "burn_down_usd",
    }
    aggregated = _aggregate_numeric(rows, group_fields=group_fields, numeric_mapping=numeric_mapping)

    results: list[dict[str, Any]] = []
    for record in aggregated:
        record.setdefault("commitment_usd", Decimal("0"))
        record.setdefault("accrual_usd", Decimal("0"))
        record.setdefault("cash_usd", Decimal("0"))
        record.setdefault("open_commitment_usd", Decimal("0"))
        record.setdefault("variance_usd", Decimal("0"))
        record.setdefault("variance_pct", None)
        results.append(_finalise_numeric(record))

    return _paginate(results, limit=limit, offset=offset)


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.PurchaseOrder)).scalars().all()


@router.post("/purchase-orders", response_model=PurchaseOrderOut)
def create_purchase_order(payload: PurchaseOrderIn, db: Session = Depends(get_db)):
    po = models_finance.PurchaseOrder(**payload.model_dump(exclude={"lines"}))
    db.add(po)
    db.flush()
    for line in payload.lines:
        db.add(models_finance.POLine(purchase_order=po, **line.model_dump()))
    db.commit()
    db.refresh(po)
    return po


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(po_id: int, db: Session = Depends(get_db)):
    po = db.get(models_finance.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    return po


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def update_purchase_order(po_id: int, payload: PurchaseOrderIn, db: Session = Depends(get_db)):
    po = db.get(models_finance.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    for key, value in payload.model_dump(exclude={"lines"}).items():
        setattr(po, key, value)
    po.lines.clear()
    db.flush()
    for line in payload.lines:
        db.add(models_finance.POLine(purchase_order=po, **line.model_dump()))
    db.commit()
    db.refresh(po)
    return po


@router.delete("/purchase-orders/{po_id}")
def delete_purchase_order(po_id: int, db: Session = Depends(get_db)):
    po = db.get(models_finance.PurchaseOrder, po_id)
    if not po:
        return {"ok": True}
    db.delete(po)
    db.commit()
    return {"ok": True}


@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.Invoice)).scalars().all()


@router.post("/invoices", response_model=InvoiceOut)
def create_invoice(payload: InvoiceIn, db: Session = Depends(get_db)):
    invoice = models_finance.Invoice(**payload.model_dump(exclude={"lines"}))
    db.add(invoice)
    db.flush()
    for line in payload.lines:
        db.add(models_finance.InvoiceLine(invoice=invoice, **line.model_dump()))
    db.commit()
    db.refresh(invoice)
    return invoice


@router.put("/invoices/{invoice_id}", response_model=InvoiceOut)
def update_invoice(invoice_id: int, payload: InvoiceIn, db: Session = Depends(get_db)):
    invoice = db.get(models_finance.Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    for key, value in payload.model_dump(exclude={"lines"}).items():
        setattr(invoice, key, value)
    invoice.lines.clear()
    db.flush()
    for line in payload.lines:
        db.add(models_finance.InvoiceLine(invoice=invoice, **line.model_dump()))
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/payment-schedules", response_model=list[PaymentScheduleOut])
def list_payment_schedules(
    funding_source_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    vendor_id: Optional[int] = Query(default=None),
    po_id: Optional[int] = Query(default=None),
    invoice_id: Optional[int] = Query(default=None),
    due_from: Optional[dt.date] = Query(default=None),
    due_to: Optional[dt.date] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(models_finance.PaymentSchedule).options(
        selectinload(models_finance.PaymentSchedule.purchase_order),
        selectinload(models_finance.PaymentSchedule.invoice),
    )
    if po_id is not None:
        stmt = stmt.where(models_finance.PaymentSchedule.purchase_order_id == po_id)
    if invoice_id is not None:
        stmt = stmt.where(models_finance.PaymentSchedule.invoice_id == invoice_id)
    if status is not None:
        stmt = stmt.where(models_finance.PaymentSchedule.status == status)
    if due_from is not None:
        stmt = stmt.where(models_finance.PaymentSchedule.due_date >= due_from)
    if due_to is not None:
        stmt = stmt.where(models_finance.PaymentSchedule.due_date <= due_to)

    schedules = db.execute(stmt).scalars().all()

    filtered: list[models_finance.PaymentSchedule] = []
    for schedule in schedules:
        fs_id = None
        proj_id = None
        vend_id = None
        if schedule.purchase_order:
            fs_id = schedule.purchase_order.funding_source_id
            proj_id = schedule.purchase_order.project_id
            vend_id = schedule.purchase_order.vendor_id
        if schedule.invoice:
            vend_id = schedule.invoice.vendor_id or vend_id
            if schedule.invoice.purchase_order:
                po_ref = schedule.invoice.purchase_order
                fs_id = fs_id or po_ref.funding_source_id
                proj_id = proj_id or po_ref.project_id
                vend_id = vend_id or po_ref.vendor_id
        if funding_source_id is not None and fs_id != funding_source_id:
            continue
        if project_id is not None and proj_id != project_id:
            continue
        if vendor_id is not None and vend_id != vendor_id:
            continue
        filtered.append(schedule)

    return filtered[offset : offset + limit]


@router.post("/payment-schedules", response_model=PaymentScheduleOut)
def create_payment_schedule(payload: PaymentScheduleIn, db: Session = Depends(get_db)):
    schedule = models_finance.PaymentSchedule(**payload.model_dump())
    db.add(schedule)
    db.flush()
    _emit_event(
        db,
        entity_type="payment_schedule",
        entity_id=schedule.id,
        event_type="payment_schedule_created",
        payload=_jsonify(payload.model_dump()),
    )
    db.commit()
    db.refresh(schedule)
    return schedule


@router.post("/payment-schedules/generate", response_model=list[PaymentScheduleOut])
def payment_schedule_generate(payload: PaymentScheduleGenerateV2Request, db: Session = Depends(get_db)):
    schedules = _generate_payment_schedule_records(db, payload)
    db.commit()
    for schedule in schedules:
        db.refresh(schedule)
    return schedules


@router.post("/payment-schedule/generate", response_model=list[PaymentScheduleOut])
def payment_schedule_generate_legacy(payload: PaymentScheduleGenerateRequest, db: Session = Depends(get_db)):
    modern_payload = PaymentScheduleGenerateV2Request.model_validate(
        {
            "invoice_id": payload.invoice_id,
            "po_id": payload.purchase_order_id,
            "rule": "NET_N",
            "net_days": payload.net_days,
            "splits": [],
            "by": "system",
        }
    )
    schedules = _generate_payment_schedule_records(db, modern_payload)
    db.commit()
    for schedule in schedules:
        db.refresh(schedule)
    return schedules


@router.put("/payment-schedules/{schedule_id}", response_model=PaymentScheduleOut)
def update_payment_schedule(
    schedule_id: int,
    payload: PaymentScheduleUpdateIn,
    db: Session = Depends(get_db),
):
    schedule = db.get(models_finance.PaymentSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Payment schedule not found")

    updates = payload.model_dump(exclude_unset=True)
    if schedule.paid_transaction_id and any(field in updates for field in {"amount", "percent"}):
        raise HTTPException(status_code=400, detail="Cannot modify amount/percent once paid")

    for key, value in updates.items():
        setattr(schedule, key, value)

    db.commit()
    db.refresh(schedule)
    _emit_event(
        db,
        entity_type="payment_schedule",
        entity_id=schedule.id,
        event_type="payment_schedule_updated",
        payload=_jsonify(updates),
    )
    return schedule


@router.delete("/payment-schedules/{schedule_id}")
def delete_payment_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.get(models_finance.PaymentSchedule, schedule_id)
    if not schedule:
        return {"ok": True}
    if schedule.paid_transaction_id:
        raise HTTPException(status_code=400, detail="Cannot delete a paid schedule")
    db.delete(schedule)
    db.flush()
    _emit_event(
        db,
        entity_type="payment_schedule",
        entity_id=schedule_id,
        event_type="payment_schedule_deleted",
    )
    db.commit()
    return {"ok": True}


@router.get("/fx-rates", response_model=list[FxRateOut])
def list_fx_rates(
    quote_currency: Optional[str] = Query(default=None),
    valid_from: Optional[dt.date] = Query(default=None),
    valid_to: Optional[dt.date] = Query(default=None),
    active_on: Optional[dt.date] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(models_finance.FxRate)
    if quote_currency:
        stmt = stmt.where(models_finance.FxRate.quote_currency == quote_currency.upper())
    if valid_from:
        stmt = stmt.where(models_finance.FxRate.valid_from >= valid_from)
    if valid_to:
        stmt = stmt.where(
            or_(
                models_finance.FxRate.valid_to.is_(None),
                models_finance.FxRate.valid_to <= valid_to,
            )
        )

    rates = db.execute(stmt).scalars().all()
    if active_on:
        active_rates = []
        for rate in rates:
            if rate.valid_from and rate.valid_from > active_on:
                continue
            if rate.valid_to and rate.valid_to < active_on:
                continue
            active_rates.append(rate)
        rates = active_rates
    return rates[offset : offset + limit]


@router.post("/fx-rates", response_model=FxRateOut)
def create_fx_rate(payload: FxRateIn, db: Session = Depends(get_db)):
    if not (Decimal("0.5") <= payload.rate <= Decimal("2.0")) and not payload.manual_override:
        raise HTTPException(status_code=400, detail="FX rate out of safety bounds")
    body = payload.model_dump()
    body["quote_currency"] = body["quote_currency"].upper()
    rate = models_finance.FxRate(**body)
    db.add(rate)
    db.flush()
    _emit_event(
        db,
        entity_type="fx_rate",
        entity_id=rate.id,
        event_type="fx_rate_created",
        payload=_jsonify(body),
    )
    db.commit()
    db.refresh(rate)
    return rate


@router.put("/fx-rates/{rate_id}", response_model=FxRateOut)
def update_fx_rate(rate_id: int, payload: FxRateUpdateIn, db: Session = Depends(get_db)):
    rate = db.get(models_finance.FxRate, rate_id)
    if not rate:
        raise HTTPException(status_code=404, detail="FX rate not found")

    updates = payload.model_dump(exclude_unset=True)
    if "quote_currency" in updates and updates["quote_currency"]:
        updates["quote_currency"] = updates["quote_currency"].upper()
    if "rate" in updates and updates["rate"] is not None:
        rate_value = _to_decimal(updates["rate"])
        if not (Decimal("0.5") <= rate_value <= Decimal("2.0")) and not (payload.manual_override or rate.manual_override):
            raise HTTPException(status_code=400, detail="FX rate out of safety bounds")
        updates["rate"] = rate_value
    for key, value in updates.items():
        setattr(rate, key, value)

    db.commit()
    db.refresh(rate)
    _emit_event(
        db,
        entity_type="fx_rate",
        entity_id=rate.id,
        event_type="fx_rate_updated",
        payload=_jsonify(updates),
    )
    return rate


@router.delete("/fx-rates/{rate_id}")
def delete_fx_rate(rate_id: int, db: Session = Depends(get_db)):
    rate = db.get(models_finance.FxRate, rate_id)
    if not rate:
        return {"ok": True}

    txn_query = select(models_finance.Transaction.id).where(
        models_finance.Transaction.currency == rate.quote_currency
    ).where(models_finance.Transaction.txn_date >= rate.valid_from)
    if rate.valid_to:
        txn_query = txn_query.where(models_finance.Transaction.txn_date <= rate.valid_to)
    txn_used = db.execute(txn_query.limit(1)).scalar_one_or_none()
    if txn_used:
        raise HTTPException(status_code=400, detail="FX rate currently referenced by transactions")

    db.delete(rate)
    db.flush()
    _emit_event(
        db,
        entity_type="fx_rate",
        entity_id=rate_id,
        event_type="fx_rate_deleted",
    )
    db.commit()
    return {"ok": True}


@router.post("/reallocate")
def reallocate(req: ReallocateRequest, db: Session = Depends(get_db)):
    txn = db.get(models_finance.Transaction, req.transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    target_fs = db.get(models_finance.FundingSource, req.target_funding_source_id)
    if not target_fs:
        raise HTTPException(status_code=404, detail="Funding source not found")
    reverse, replacement = models_finance.Transaction.create_reversal_pair(
        db,
        txn,
        reason=req.memo,
        by=req.by,
        memo_suffix="reallocate",
    )
    replacement.funding_source = target_fs
    replacement.amount_txn = Decimal(req.amount)
    replacement.amount_usd = replacement.amount_txn * replacement.fx_rate_to_usd
    db.commit()
    return {"reverse_id": reverse.id, "replacement_id": replacement.id}


@router.get("/deliverables", response_model=list[DeliverableLotOut])
def list_deliverables(
    po_id: Optional[int] = Query(default=None),
    po_line_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    late_only: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(models_finance.FulfillmentLot).options(
        selectinload(models_finance.FulfillmentLot.milestones),
        selectinload(models_finance.FulfillmentLot.po_line).selectinload(models_finance.POLine.purchase_order),
    )
    lots = db.execute(stmt).scalars().all()
    results: list[DeliverableLotOut] = []
    for lot in lots:
        purchase_order = lot.po_line.purchase_order if lot.po_line else None
        if po_id is not None and (not purchase_order or purchase_order.id != po_id):
            continue
        if po_line_id is not None and lot.po_line_id != po_line_id:
            continue
        if status is not None and not any(m.status == status for m in lot.milestones):
            continue
        late_flag = any(
            m.planned_date and not m.actual_date and m.planned_date < dt.date.today()
            for m in lot.milestones
        )
        if late_only and not late_flag:
            continue
        results.append(_serialize_lot(lot))
    return results[offset : offset + limit]


@router.get("/deliverables/checkpoints", response_model=list[CheckpointTypeOut])
def list_checkpoint_types(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.CheckpointType)).scalars().all()


@router.post("/deliverables/template/apply", response_model=list[DeliverableLotOut])
def apply_deliverable_template(payload: DeliverableTemplateApplyRequest, db: Session = Depends(get_db)):
    po = db.get(models_finance.PurchaseOrder, payload.purchase_order_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    if not payload.checkpoint_type_ids:
        raise HTTPException(status_code=400, detail="checkpoint_type_ids required")

    target_lines = (
        [line for line in po.lines if line.id in set(payload.po_line_ids or [])]
        if payload.po_line_ids
        else list(po.lines)
    )
    if not target_lines:
        raise HTTPException(status_code=400, detail="No matching PO lines for template")

    quantities = payload.lot_quantities or [line.quantity for line in target_lines if line.quantity] or [Decimal("0")]

    lots_created: list[models_finance.FulfillmentLot] = []
    for line in target_lines:
        for qty in quantities:
            lot = models_finance.FulfillmentLot(
                po_line=line,
                lot_qty=_to_decimal(qty),
            )
            db.add(lot)
            db.flush()
            _emit_event(
                db,
                entity_type="fulfillment_lot",
                entity_id=lot.id,
                event_type="lot_created",
                by=payload.by,
                payload={"po_line_id": line.id, "qty": float(_to_decimal(qty))},
            )
            for checkpoint_id in payload.checkpoint_type_ids:
                milestone = models_finance.MilestoneInstance(
                    lot=lot,
                    checkpoint_type_id=checkpoint_id,
                    planned_date=dt.date.today(),
                    status="PENDING",
                )
                db.add(milestone)
                db.flush()
                _emit_event(
                    db,
                    entity_type="milestone",
                    entity_id=milestone.id,
                    event_type="milestone_created",
                    by=payload.by,
                    payload={"checkpoint_type_id": checkpoint_id},
                )
            lots_created.append(lot)

    _emit_event(
        db,
        entity_type="purchase_order",
        entity_id=po.id,
        event_type="deliverable_template_applied",
        by=payload.by,
        payload={"po_line_ids": payload.po_line_ids or [line.id for line in target_lines]},
    )

    db.commit()
    for lot in lots_created:
        db.refresh(lot)
    return [_serialize_lot(lot) for lot in lots_created]


@router.post("/po-lines/{po_line_id}/lots", response_model=DeliverableLotOut)
def create_fulfillment_lot(po_line_id: int, payload: LotCreateIn, db: Session = Depends(get_db)):
    po_line = db.get(models_finance.POLine, po_line_id)
    if not po_line:
        raise HTTPException(status_code=404, detail="PO line not found")
    lot = models_finance.FulfillmentLot(
        po_line=po_line,
        lot_qty=_to_decimal(payload.lot_qty),
        lot_identifier=payload.lot_identifier,
        notes=payload.notes,
    )
    db.add(lot)
    db.flush()
    _emit_event(
        db,
        entity_type="fulfillment_lot",
        entity_id=lot.id,
        event_type="lot_created",
        payload={"po_line_id": po_line_id, "qty": float(_to_decimal(payload.lot_qty))},
    )
    db.commit()
    db.refresh(lot)
    return _serialize_lot(lot)


@router.put("/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(milestone_id: int, payload: MilestoneUpdateIn, db: Session = Depends(get_db)):
    milestone = db.get(models_finance.MilestoneInstance, milestone_id)
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    updates = payload.model_dump(exclude_unset=True)

    for key, value in updates.items():
        if hasattr(milestone, key) and value is not None:
            setattr(milestone, key, value)

    if payload.actual_date and payload.status is None:
        milestone.status = "COMPLETED"

    db.commit()
    db.refresh(milestone)
    event_payload = {
        key: (value.isoformat() if isinstance(value, dt.date) else value)
        for key, value in updates.items()
    }
    _emit_event(
        db,
        entity_type="milestone",
        entity_id=milestone.id,
        event_type="milestone_marked",
        payload=event_payload,
    )
    return MilestoneOut.model_validate(milestone)


@router.post("/reports", response_model=ReportDefinitionOut)
def create_report(payload: ReportDefinitionIn, db: Session = Depends(get_db)):
    report = models_finance.ReportDefinition(**payload.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("/reports", response_model=list[ReportDefinitionOut])
def list_reports(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.ReportDefinition)).scalars().all()


@router.post("/report/save", response_model=ReportDefinitionOut)
def save_report(payload: ReportDefinitionIn, db: Session = Depends(get_db)):
    report = models_finance.ReportDefinition(**payload.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("/report/run/{report_id}", response_model=SavedReportResult)
def run_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(models_finance.ReportDefinition, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    view_name = report.json_config.get("view")
    if not view_name:
        raise HTTPException(status_code=400, detail="Report missing view name in json_config")
    apply_views(db.bind)
    rows = [dict(r._mapping) for r in db.execute(text(f"SELECT * FROM {view_name}"))]
    return SavedReportResult(rows=rows, generated_at=dt.datetime.utcnow())


@router.post("/report/run", response_model=SavedReportResult)
def run_report_adhoc(payload: ReportRunIn, db: Session = Depends(get_db)):
    view_name = payload.json_config.get("view")
    if not view_name:
        raise HTTPException(status_code=400, detail="json_config.view is required")
    apply_views(db.bind)
    rows = [dict(r._mapping) for r in db.execute(text(f"SELECT * FROM {view_name}"))]
    return SavedReportResult(rows=rows, generated_at=dt.datetime.utcnow())
