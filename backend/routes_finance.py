from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import get_db
from . import models_finance
from .schemas_finance import (
    DeliverableTemplateApplyRequest,
    FxRateIn,
    FxRateOut,
    FundingSourceIn,
    FundingSourceOut,
    InvoiceIn,
    InvoiceOut,
    PaymentScheduleGenerateRequest,
    PaymentScheduleIn,
    PaymentScheduleOut,
    PurchaseOrderIn,
    PurchaseOrderOut,
    ReallocateRequest,
    ReportDefinitionIn,
    ReportDefinitionOut,
    SavedReportResult,
)
from .schemas_finance import FulfillmentLotOut
from .sql.views import apply_views

router = APIRouter(prefix="/api", tags=["finance"])


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
def list_payment_schedules(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.PaymentSchedule)).scalars().all()


@router.post("/payment-schedules", response_model=PaymentScheduleOut)
def create_payment_schedule(payload: PaymentScheduleIn, db: Session = Depends(get_db)):
    schedule = models_finance.PaymentSchedule(**payload.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.post("/payment-schedule/generate", response_model=list[PaymentScheduleOut])
def generate_payment_schedule(payload: PaymentScheduleGenerateRequest, db: Session = Depends(get_db)):
    invoice = db.get(models_finance.Invoice, payload.invoice_id) if payload.invoice_id else None
    po = db.get(models_finance.PurchaseOrder, payload.purchase_order_id) if payload.purchase_order_id else None
    if not invoice and not po:
        raise HTTPException(status_code=400, detail="invoice_id or purchase_order_id required")
    schedules = models_finance.PaymentSchedule.generate_default(
        session=db,
        invoice=invoice,
        purchase_order=po,
        net_days=payload.net_days,
    )
    db.commit()
    return schedules


@router.post("/fx-rates", response_model=FxRateOut)
def create_fx_rate(payload: FxRateIn, db: Session = Depends(get_db)):
    if not (Decimal("0.1") <= payload.rate <= Decimal("10")) and not payload.manual_override:
        raise HTTPException(status_code=400, detail="FX rate out of safety bounds")
    rate = models_finance.FxRate(**payload.model_dump())
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return rate


@router.get("/fx-rates", response_model=list[FxRateOut])
def list_fx_rates(db: Session = Depends(get_db)):
    return db.execute(select(models_finance.FxRate)).scalars().all()


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


@router.post("/deliverables/template/apply", response_model=list[FulfillmentLotOut])
def apply_deliverable_template(payload: DeliverableTemplateApplyRequest, db: Session = Depends(get_db)):
    po = db.get(models_finance.PurchaseOrder, payload.purchase_order_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    lots_created: list[models_finance.FulfillmentLot] = []
    for line in po.lines:
        for qty in payload.lot_quantities:
            lot = models_finance.FulfillmentLot(po_line=line, lot_qty=qty)
            db.add(lot)
            db.flush()
            for checkpoint_id in payload.checkpoint_type_ids:
                milestone = models_finance.MilestoneInstance(
                    lot=lot,
                    checkpoint_type_id=checkpoint_id,
                    planned_date=dt.date.today(),
                    status="PENDING",
                )
                db.add(milestone)
            lots_created.append(lot)
    db.commit()
    return lots_created


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
