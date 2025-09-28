"""New financial domain models for the immutable ledger and workflow timeline."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

FundingSourceType = Enum("CAR", "COST_CENTER", name="funding_source_type", create_constraint=False)
TransactionState = Enum("FORECAST", "COMMITMENT", "ACCRUAL", "CASH", name="transaction_state", create_constraint=False)
TransactionSourceType = Enum(
    "QUOTE", "PO", "INVOICE", "PAYMENT", "JOURNAL", name="transaction_source_type", create_constraint=False
)
PaymentDueRule = Enum("NET_N", "ON_EVENT", "NET_0", name="payment_due_rule", create_constraint=False)
PaymentScheduleStatus = Enum("PLANNED", "DUE", "PAID", "CANCELLED", name="payment_schedule_status", create_constraint=False)


class FundingSource(Base):
    __tablename__ = "funding_sources"
    __table_args__ = (
        UniqueConstraint("name", name="uq_funding_source_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(FundingSourceType, default="COST_CENTER", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[Optional[str]] = mapped_column(String(255))
    car_code: Mapped[Optional[str]] = mapped_column(String(50))
    cc_code: Mapped[Optional[str]] = mapped_column(String(50))
    closure_date: Mapped[Optional[dt.date]] = mapped_column(Date())
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_cost_center: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    budget_amount_cache: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(100))
    updated_by: Mapped[Optional[str]] = mapped_column(String(100))
    legacy_portfolio_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True)
    legacy_fiscal_year: Mapped[Optional[str]] = mapped_column(String(20))
    legacy_owner: Mapped[Optional[str]] = mapped_column(String(255))

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="funding_source")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="funding_source")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="funding_source")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<FundingSource id={self.id} type={self.type} name={self.name!r} is_cc={self.is_cost_center}>"

    @classmethod
    def ensure(cls, session, *, name: str, type: str = "COST_CENTER", **kwargs: Any) -> "FundingSource":
        obj = session.query(cls).filter_by(name=name).one_or_none()
        if obj:
            return obj
        obj = cls(name=name, type=type, **kwargs)
        session.add(obj)
        session.flush()
        return obj


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("quote_currency", "valid_from", name="uq_fx_quote_from"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[dt.date]] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FxRate {self.quote_currency} {self.valid_from}={self.rate}>"

    @classmethod
    def lookup(cls, session, target_date: dt.date, currency: str, *, allow_stale: bool = False) -> "FxRate":
        currency = currency.upper()
        q = (
            session.query(cls)
            .filter(cls.quote_currency == currency)
            .filter(cls.valid_from <= target_date)
            .order_by(cls.valid_from.desc())
        )
        rate = q.first()
        if not rate:
            raise LookupError(f"No FX rate for {currency} on/before {target_date}")
        if not allow_stale and rate.valid_to and rate.valid_to < target_date:
            raise LookupError(f"FX rate for {currency} expired on {rate.valid_to}")
        return rate


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    funding_source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("funding_sources.id"))
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    quote_number: Mapped[Optional[str]] = mapped_column(String(64))
    issued_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=1, nullable=False)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    memo: Mapped[Optional[str]] = mapped_column(Text)

    funding_source: Mapped[Optional[FundingSource]] = relationship(back_populates="quotes")
    lines: Mapped[list["QuoteLine"]] = relationship(back_populates="quote", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Quote id={self.id} number={self.quote_number!r}>"


class QuoteLine(Base):
    __tablename__ = "quote_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    expected_date: Mapped[Optional[dt.date]] = mapped_column(Date)

    quote: Mapped[Quote] = relationship(back_populates="lines")
    po_lines: Mapped[list["POLine"]] = relationship("POLine", back_populates="quote_line")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<QuoteLine id={self.id} desc={self.description[:20]!r}>"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    funding_source_id: Mapped[int] = mapped_column(ForeignKey("funding_sources.id"), nullable=False)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    po_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ordered_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=1, nullable=False)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False)
    memo: Mapped[Optional[str]] = mapped_column(Text)

    funding_source: Mapped[FundingSource] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["POLine"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")
    payment_schedules: Mapped[list["PaymentSchedule"]] = relationship(back_populates="purchase_order")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PO number={self.po_number!r} total={self.total_amount}>"


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    quote_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quote_lines.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    deliverable_desc: Mapped[Optional[str]] = mapped_column(Text)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    quote_line: Mapped[Optional[QuoteLine]] = relationship(back_populates="po_lines")
    invoice_lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="po_line")
    lots: Mapped[list["FulfillmentLot"]] = relationship(back_populates="po_line", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<POLine id={self.id} amount={self.amount}>"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchase_orders.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=1, nullable=False)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False)
    memo: Mapped[Optional[str]] = mapped_column(Text)

    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payment_schedules: Mapped[list["PaymentSchedule"]] = relationship(back_populates="invoice")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Invoice number={self.invoice_number!r} total={self.total_amount}>"


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    po_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("po_lines.id"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    po_line: Mapped[Optional[POLine]] = relationship(back_populates="invoice_lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvoiceLine id={self.id} amount={self.amount}>"


class POLineQuoteLine(Base):
    __tablename__ = "po_line_quote_line"
    po_line_id: Mapped[int] = mapped_column(ForeignKey("po_lines.id", ondelete="CASCADE"), primary_key=True)
    quote_line_id: Mapped[int] = mapped_column(ForeignKey("quote_lines.id", ondelete="CASCADE"), primary_key=True)


class CheckpointType(Base):
    __tablename__ = "checkpoint_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CheckpointType code={self.code}>"


class FulfillmentLot(Base):
    __tablename__ = "fulfillment_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("po_lines.id", ondelete="CASCADE"), nullable=False)
    lot_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    lot_identifier: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    po_line: Mapped[POLine] = relationship(back_populates="lots")
    milestones: Mapped[list["MilestoneInstance"]] = relationship(back_populates="lot", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FulfillmentLot id={self.id} qty={self.lot_qty}>"


class MilestoneInstance(Base):
    __tablename__ = "milestone_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    fulfillment_lot_id: Mapped[int] = mapped_column(ForeignKey("fulfillment_lots.id", ondelete="CASCADE"), nullable=False)
    checkpoint_type_id: Mapped[int] = mapped_column(ForeignKey("checkpoint_types.id"), nullable=False)
    planned_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    actual_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)

    lot: Mapped[FulfillmentLot] = relationship(back_populates="milestones")
    checkpoint_type: Mapped[CheckpointType] = relationship()
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        secondary="transaction_deliverables",
        back_populates="deliverables",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MilestoneInstance id={self.id} status={self.status}>"


class PaymentSchedule(Base):
    __tablename__ = "payment_schedules"
    __table_args__ = (
        CheckConstraint("percent IS NULL OR percent >= 0", name="ck_payment_percent_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchase_orders.id"))
    invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"))
    percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    due_date_rule: Mapped[str] = mapped_column(PaymentDueRule, default="NET_N", nullable=False)
    net_days: Mapped[Optional[int]] = mapped_column(Integer)
    event_type: Mapped[Optional[str]] = mapped_column(String(50))
    due_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(PaymentScheduleStatus, default="PLANNED", nullable=False)
    paid_transaction_id: Mapped[Optional[str]] = mapped_column(ForeignKey("transactions.id"))

    purchase_order: Mapped[Optional[PurchaseOrder]] = relationship(back_populates="payment_schedules")
    invoice: Mapped[Optional[Invoice]] = relationship(back_populates="payment_schedules")
    paid_transaction: Mapped[Optional["Transaction"]] = relationship(foreign_keys=[paid_transaction_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PaymentSchedule id={self.id} status={self.status}>"

    @classmethod
    def generate_default(
        cls,
        *,
        session,
        invoice: Optional[Invoice] = None,
        purchase_order: Optional[PurchaseOrder] = None,
        net_days: int = 60,
        percent: Optional[Decimal] = Decimal("1.0"),
    ) -> list["PaymentSchedule"]:
        if not invoice and not purchase_order:
            raise ValueError("Either invoice or purchase_order required")
        due_date = None
        if invoice and invoice.invoice_date:
            due_date = invoice.invoice_date + dt.timedelta(days=net_days)
        schedules: list[PaymentSchedule] = []
        schedule = cls(
            invoice=invoice,
            purchase_order=purchase_order,
            due_date_rule="NET_N" if net_days else "NET_0",
            net_days=net_days,
            percent=percent,
            due_date=due_date,
            status="PLANNED",
        )
        session.add(schedule)
        session.flush()
        schedules.append(schedule)
        return schedules


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    by: Mapped[Optional[str]] = mapped_column(String(100))
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event {self.entity_type}:{self.event_type} at={self.at}>"


class ReportDefinition(Base):
    __tablename__ = "report_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    json_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReportDefinition id={self.id} name={self.name!r}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    funding_source_id: Mapped[int] = mapped_column(ForeignKey("funding_sources.id"), nullable=False)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    state: Mapped[str] = mapped_column(TransactionState, nullable=False)
    source_type: Mapped[str] = mapped_column(TransactionSourceType, nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(64))
    amount_txn: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("1.0"), nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    txn_date: Mapped[dt.date] = mapped_column(Date, default=dt.date.today, nullable=False)
    memo: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list[str]]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    reverses_transaction_id: Mapped[Optional[str]] = mapped_column(ForeignKey("transactions.id"))
    reversed_by_transaction_id: Mapped[Optional[str]] = mapped_column(String(36), unique=True)

    funding_source: Mapped[FundingSource] = relationship(back_populates="transactions", foreign_keys=[funding_source_id])
    reversed_transaction: Mapped[Optional["Transaction"]] = relationship("Transaction", remote_side=[id], foreign_keys=[reverses_transaction_id])
    deliverables: Mapped[list[MilestoneInstance]] = relationship(
        "MilestoneInstance",
        secondary="transaction_deliverables",
        back_populates="transactions",
    )
    po_lines: Mapped[list[POLine]] = relationship(
        "POLine",
        secondary="transaction_po_lines",
        backref="transactions",
    )
    invoice_lines: Mapped[list[InvoiceLine]] = relationship(
        "InvoiceLine",
        secondary="transaction_invoice_lines",
        backref="transactions",
    )
    payment_schedule: Mapped[Optional[PaymentSchedule]] = relationship(
        PaymentSchedule, back_populates="paid_transaction", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transaction id={self.id} state={self.state} amount={self.amount_txn} {self.currency}>"

    @classmethod
    def create(
        cls,
        session,
        *,
        funding_source: FundingSource,
        state: str,
        source_type: str,
        amount_txn: Decimal,
        currency: str = "USD",
        fx_rate_to_usd: Optional[Decimal] = None,
        **kwargs: Any,
    ) -> "Transaction":
        currency = currency.upper()
        if fx_rate_to_usd is None:
            rate = FxRate.lookup(session, kwargs.get("txn_date", dt.date.today()), currency)
            fx_rate_to_usd = rate.rate
        amount_usd = Decimal(amount_txn) * Decimal(fx_rate_to_usd)
        tx = cls(
            funding_source=funding_source,
            state=state,
            source_type=source_type,
            amount_txn=Decimal(amount_txn),
            currency=currency,
            fx_rate_to_usd=Decimal(fx_rate_to_usd),
            amount_usd=amount_usd.quantize(Decimal("0.000001")),
            **kwargs,
        )
        session.add(tx)
        session.flush()
        return tx

    @classmethod
    def create_reversal_pair(
        cls,
        session,
        original: "Transaction",
        *,
        reason: str,
        by: str,
        memo_suffix: str | None = None,
    ) -> tuple["Transaction", "Transaction"]:
        reverse = cls(
            funding_source=original.funding_source,
            state=original.state,
            source_type="JOURNAL",
            source_id=original.id,
            amount_txn=-original.amount_txn,
            currency=original.currency,
            fx_rate_to_usd=original.fx_rate_to_usd,
            amount_usd=-original.amount_usd,
            txn_date=dt.date.today(),
            memo=f"Reversal of {original.id}: {reason}" + (f" ({memo_suffix})" if memo_suffix else ""),
            tags=original.tags,
            reverses_transaction_id=original.id,
        )
        session.add(reverse)
        session.flush()

        replacement = cls(
            funding_source=original.funding_source,
            state=original.state,
            source_type=original.source_type,
            source_id=original.source_id,
            amount_txn=original.amount_txn,
            currency=original.currency,
            fx_rate_to_usd=original.fx_rate_to_usd,
            amount_usd=original.amount_usd,
            txn_date=dt.date.today(),
            memo=f"Replacement for {original.id}: {reason}" + (f" ({memo_suffix})" if memo_suffix else ""),
            tags=original.tags,
        )
        session.add(replacement)
        session.flush()
        reverse.reversed_by_transaction_id = replacement.id
        original.reversed_by_transaction_id = reverse.id

        session.add(
            Event(
                entity_type="transaction",
                entity_id=original.id,
                event_type="reversal",
                by=by,
                payload_json={"reason": reason, "replacement_id": replacement.id, "reverse_id": reverse.id},
            )
        )
        return reverse, replacement


class TransactionPOLine(Base):
    __tablename__ = "transaction_po_lines"
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("po_lines.id", ondelete="CASCADE"), primary_key=True)


class TransactionInvoiceLine(Base):
    __tablename__ = "transaction_invoice_lines"
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True)
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("invoice_lines.id", ondelete="CASCADE"), primary_key=True)


class TransactionDeliverable(Base):
    __tablename__ = "transaction_deliverables"
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True)
    deliverable_id: Mapped[int] = mapped_column(ForeignKey("milestone_instances.id", ondelete="CASCADE"), primary_key=True)
