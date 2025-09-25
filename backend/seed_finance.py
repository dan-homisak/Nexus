"""Development seed for the expanded finance domain."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select

from backend.db import SessionLocal
from backend import models, models_finance


def seed():
    session = SessionLocal()
    try:
        car = models_finance.FundingSource.ensure(session, name="CAR-Alpha", type="CAR", is_temporary=False)
        cc = models_finance.FundingSource.ensure(session, name="CC-Temp", type="COST_CENTER", is_temporary=True)

        vendor = session.execute(select(models.Vendor)).scalar_one_or_none()
        if not vendor:
            vendor = models.Vendor(name="Default Vendor")
            session.add(vendor)
            session.flush()

        po = models_finance.PurchaseOrder(
            funding_source=car,
            vendor_id=vendor.id,
            po_number="PO-1001",
            ordered_date=dt.date.today(),
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            status="OPEN",
        )
        po.lines = [
            models_finance.POLine(description="Line 1", quantity=Decimal("10"), unit_price=Decimal("100"), amount=Decimal("1000")),
        ]
        session.add(po)

        lot1 = models_finance.FulfillmentLot(po_line=po.lines[0], lot_qty=Decimal("5"), lot_identifier="Lot-A")
        lot2 = models_finance.FulfillmentLot(po_line=po.lines[0], lot_qty=Decimal("5"), lot_identifier="Lot-B")
        session.add_all([lot1, lot2])
        ct_ship = models_finance.CheckpointType(code="oem_ship", name="OEM Ship")
        ct_arrive = models_finance.CheckpointType(code="arrive_plant", name="Arrive Plant")
        session.add_all([ct_ship, ct_arrive])
        session.flush()
        for lot in (lot1, lot2):
            for ct in (ct_ship, ct_arrive):
                session.add(models_finance.MilestoneInstance(lot=lot, checkpoint_type_id=ct.id, planned_date=dt.date.today()))

        invoice = models_finance.Invoice(
            purchase_order=po,
            vendor_id=vendor.id,
            invoice_number="INV-5001",
            invoice_date=dt.date.today(),
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            status="OPEN",
        )
        invoice.lines = [
            models_finance.InvoiceLine(description="First shipment", quantity=Decimal("5"), unit_price=Decimal("100"), amount=Decimal("500")),
        ]
        session.add(invoice)
        session.flush()

        models_finance.PaymentSchedule.generate_default(session=session, invoice=invoice, net_days=60)

        txn = models_finance.Transaction(
            funding_source=car,
            state="COMMITMENT",
            source_type="PO",
            source_id=str(po.id),
            amount_txn=Decimal("1000"),
            currency="USD",
            fx_rate_to_usd=Decimal("1.0"),
            amount_usd=Decimal("1000"),
            txn_date=dt.date.today(),
        )
        session.add(txn)
        session.flush()
        models_finance.Event(
            entity_type="purchase_order",
            entity_id=str(po.id),
            event_type="po_issued",
            at=dt.datetime.utcnow(),
            by="seed",
            payload_json={"po_number": po.po_number},
        )

        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    seed()
