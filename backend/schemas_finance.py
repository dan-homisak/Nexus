"""Pydantic schemas for the expanded financial domain."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FundingSourceIn(BaseModel):
    name: str
    type: str = Field(default="COST_CENTER")
    car_code: Optional[str] = None
    cc_code: Optional[str] = None
    closure_date: Optional[date] = None
    is_temporary: bool = False
    legacy_portfolio_id: Optional[int] = None
    legacy_fiscal_year: Optional[str] = None
    legacy_owner: Optional[str] = None


class FundingSourceOut(FundingSourceIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class QuoteLineIn(BaseModel):
    description: str
    quantity: Decimal = Decimal("0")
    unit_cost: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    category_id: Optional[int] = None
    expected_date: Optional[date] = None


class QuoteIn(BaseModel):
    funding_source_id: Optional[int] = None
    project_id: Optional[int] = None
    vendor_id: Optional[int] = None
    quote_number: Optional[str] = None
    issued_date: Optional[date] = None
    currency: str = "USD"
    fx_rate_to_usd: Decimal = Decimal("1.0")
    total_amount: Optional[Decimal] = None
    amount_usd: Optional[Decimal] = None
    memo: Optional[str] = None
    lines: List[QuoteLineIn] = Field(default_factory=list)


class QuoteOut(QuoteIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class POLineIn(BaseModel):
    description: str
    quantity: Decimal = Decimal("0")
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    category_id: Optional[int] = None
    deliverable_desc: Optional[str] = None
    quote_line_id: Optional[int] = None


class PurchaseOrderIn(BaseModel):
    funding_source_id: int
    project_id: Optional[int] = None
    vendor_id: Optional[int] = None
    po_number: str
    ordered_date: Optional[date] = None
    currency: str = "USD"
    fx_rate_to_usd: Decimal = Decimal("1.0")
    total_amount: Optional[Decimal] = None
    amount_usd: Optional[Decimal] = None
    status: str = "OPEN"
    memo: Optional[str] = None
    lines: List[POLineIn] = Field(default_factory=list)


class PurchaseOrderOut(PurchaseOrderIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class InvoiceLineIn(BaseModel):
    description: str
    quantity: Decimal = Decimal("0")
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    category_id: Optional[int] = None
    po_line_id: Optional[int] = None


class InvoiceIn(BaseModel):
    purchase_order_id: Optional[int] = None
    vendor_id: Optional[int] = None
    invoice_number: str
    invoice_date: Optional[date] = None
    currency: str = "USD"
    fx_rate_to_usd: Decimal = Decimal("1.0")
    total_amount: Optional[Decimal] = None
    amount_usd: Optional[Decimal] = None
    status: str = "OPEN"
    memo: Optional[str] = None
    lines: List[InvoiceLineIn] = Field(default_factory=list)


class InvoiceOut(InvoiceIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class MilestoneIn(BaseModel):
    checkpoint_type_id: int
    planned_date: Optional[date] = None
    actual_date: Optional[date] = None
    status: str = "PENDING"


class FulfillmentLotIn(BaseModel):
    po_line_id: int
    lot_qty: Decimal
    lot_identifier: Optional[str] = None
    notes: Optional[str] = None
    milestones: List[MilestoneIn] = Field(default_factory=list)


class MilestoneOut(MilestoneIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class FulfillmentLotOut(FulfillmentLotIn):
    id: int
    milestones: List[MilestoneOut]
    model_config = ConfigDict(from_attributes=True)


class PaymentScheduleIn(BaseModel):
    purchase_order_id: Optional[int] = None
    invoice_id: Optional[int] = None
    percent: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    due_date_rule: str = "NET_N"
    net_days: Optional[int] = 60
    event_type: Optional[str] = None
    due_date: Optional[date] = None
    status: str = "PLANNED"
    paid_transaction_id: Optional[str] = None


class PaymentScheduleOut(PaymentScheduleIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class FxRateIn(BaseModel):
    quote_currency: str
    valid_from: date
    valid_to: Optional[date] = None
    rate: Decimal
    manual_override: bool = False


class FxRateOut(FxRateIn):
    id: int
    base_currency: str
    model_config = ConfigDict(from_attributes=True)


class ReportDefinitionIn(BaseModel):
    name: str
    owner: str
    json_config: dict


class ReportDefinitionOut(ReportDefinitionIn):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SavedReportResult(BaseModel):
    rows: list[dict]
    generated_at: datetime


class ReallocateRequest(BaseModel):
    transaction_id: str
    target_funding_source_id: int
    amount: Decimal
    memo: str
    by: str = "system"


class PaymentScheduleGenerateRequest(BaseModel):
    invoice_id: Optional[int] = None
    purchase_order_id: Optional[int] = None
    net_days: int = 60


class DeliverableTemplateApplyRequest(BaseModel):
    purchase_order_id: int
    lot_quantities: List[Decimal]
    checkpoint_type_ids: List[int]
