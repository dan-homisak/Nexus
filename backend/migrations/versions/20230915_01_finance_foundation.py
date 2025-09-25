"""finance foundation"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

from backend.sql.views import VIEW_DEFINITIONS

revision = "20230915_01"
down_revision = None
branch_labels = None
depends_on = None

funding_source_type = sa.Enum("CAR", "COST_CENTER", name="funding_source_type")
transaction_state = sa.Enum("FORECAST", "COMMITMENT", "ACCRUAL", "CASH", name="transaction_state")
transaction_source_type = sa.Enum("QUOTE", "PO", "INVOICE", "PAYMENT", "JOURNAL", name="transaction_source_type")
payment_due_rule = sa.Enum("NET_N", "ON_EVENT", "NET_0", name="payment_due_rule")
payment_status = sa.Enum("PLANNED", "DUE", "PAID", "CANCELLED", name="payment_schedule_status")


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    def ensure_table(name: str, create_fn) -> None:
        if name not in existing_tables:
            create_fn()
            existing_tables.add(name)

    def has_index(name: str) -> bool:
        return (
            conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:name"),
                {"name": name},
            ).fetchone()
            is not None
        )

    def ensure_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
        if table not in existing_tables or has_index(name):
            return
        op.create_index(name, table, columns, unique=unique)

    ensure_table(
        "funding_sources",
        lambda: op.create_table(
            "funding_sources",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("type", funding_source_type, nullable=False, server_default="COST_CENTER"),
            sa.Column("name", sa.String(length=255), nullable=False, unique=True),
            sa.Column("car_code", sa.String(length=50), nullable=True),
            sa.Column("cc_code", sa.String(length=50), nullable=True),
            sa.Column("closure_date", sa.Date, nullable=True),
            sa.Column("is_temporary", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("legacy_portfolio_id", sa.Integer, nullable=True, unique=True),
            sa.Column("legacy_fiscal_year", sa.String(length=20), nullable=True),
            sa.Column("legacy_owner", sa.String(length=255), nullable=True),
            mysql_engine="InnoDB",
        ),
    )
    ensure_index("ix_funding_sources_type", "funding_sources", ["type"])
    ensure_index("ix_funding_sources_closure", "funding_sources", ["closure_date"])

    if "portfolios" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("portfolios")}
        if "type" not in existing_cols:
            op.add_column("portfolios", sa.Column("type", funding_source_type, nullable=True))
        if "car_code" not in existing_cols:
            op.add_column("portfolios", sa.Column("car_code", sa.String(length=50)))
        if "cc_code" not in existing_cols:
            op.add_column("portfolios", sa.Column("cc_code", sa.String(length=50)))
        if "closure_date" not in existing_cols:
            op.add_column("portfolios", sa.Column("closure_date", sa.Date))
        if "is_temporary" not in existing_cols:
            op.add_column("portfolios", sa.Column("is_temporary", sa.Boolean, server_default=sa.false()))

        if "funding_sources" in existing_tables:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO funding_sources (id, type, name, car_code, cc_code, closure_date, is_temporary, legacy_portfolio_id, legacy_fiscal_year, legacy_owner) "
                    "SELECT id, COALESCE(type, 'COST_CENTER'), name, car_code, cc_code, closure_date, COALESCE(is_temporary, 0), id, fiscal_year, owner FROM portfolios"
                )
            )

            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_portfolios_ai AFTER INSERT ON portfolios "
                    "BEGIN "
                    "INSERT OR REPLACE INTO funding_sources (id, type, name, car_code, cc_code, closure_date, is_temporary, legacy_portfolio_id, legacy_fiscal_year, legacy_owner) "
                    "VALUES (NEW.id, COALESCE(NEW.type, 'COST_CENTER'), NEW.name, NEW.car_code, NEW.cc_code, NEW.closure_date, COALESCE(NEW.is_temporary, 0), NEW.id, NEW.fiscal_year, NEW.owner); "
                    "END;"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_portfolios_au AFTER UPDATE ON portfolios "
                    "BEGIN "
                    "UPDATE funding_sources SET name = NEW.name, type = COALESCE(NEW.type, type), car_code = NEW.car_code, cc_code = NEW.cc_code, closure_date = NEW.closure_date, is_temporary = COALESCE(NEW.is_temporary, is_temporary), legacy_fiscal_year = NEW.fiscal_year, legacy_owner = NEW.owner WHERE legacy_portfolio_id = NEW.id; "
                    "END;"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER IF NOT EXISTS trg_portfolios_ad AFTER DELETE ON portfolios "
                    "BEGIN "
                    "DELETE FROM funding_sources WHERE legacy_portfolio_id = OLD.id; "
                    "END;"
                )
            )

    ensure_table(
        "transactions",
        lambda: op.create_table(
            "transactions",
            sa.Column("id", sa.String(length=36), primary_key=True, default=lambda: str(uuid4())),
            sa.Column("funding_source_id", sa.Integer, sa.ForeignKey("funding_sources.id"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
            sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id"), nullable=True),
            sa.Column("state", transaction_state, nullable=False),
            sa.Column("source_type", transaction_source_type, nullable=False),
            sa.Column("source_id", sa.String(length=64), nullable=True),
            sa.Column("amount_txn", sa.Numeric(18, 6), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("fx_rate_to_usd", sa.Numeric(18, 8), nullable=False, server_default="1.0"),
            sa.Column("amount_usd", sa.Numeric(18, 6), nullable=False),
            sa.Column("txn_date", sa.Date, nullable=False, server_default=sa.func.current_date()),
            sa.Column("memo", sa.Text, nullable=True),
            sa.Column("tags", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("reverses_transaction_id", sa.String(length=36), sa.ForeignKey("transactions.id"), nullable=True),
            sa.Column("reversed_by_transaction_id", sa.String(length=36), nullable=True, unique=True),
            mysql_engine="InnoDB",
        ),
    )
    ensure_index("ix_transactions_state", "transactions", ["state"])
    ensure_index("ix_transactions_date", "transactions", ["txn_date"])
    ensure_index("ix_transactions_funding_source", "transactions", ["funding_source_id"])

    ensure_table(
        "transaction_po_lines",
        lambda: op.create_table(
            "transaction_po_lines",
            sa.Column("transaction_id", sa.String(length=36), sa.ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("po_line_id", sa.Integer, sa.ForeignKey("po_lines.id", ondelete="CASCADE"), primary_key=True),
        ),
    )
    ensure_table(
        "transaction_invoice_lines",
        lambda: op.create_table(
            "transaction_invoice_lines",
            sa.Column("transaction_id", sa.String(length=36), sa.ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("invoice_line_id", sa.Integer, sa.ForeignKey("invoice_lines.id", ondelete="CASCADE"), primary_key=True),
        ),
    )
    ensure_table(
        "transaction_deliverables",
        lambda: op.create_table(
            "transaction_deliverables",
            sa.Column("transaction_id", sa.String(length=36), sa.ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("deliverable_id", sa.Integer, sa.ForeignKey("milestone_instances.id", ondelete="CASCADE"), primary_key=True),
        ),
    )

    ensure_table(
        "events",
        lambda: op.create_table(
            "events",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("by", sa.String(length=100), nullable=True),
            sa.Column("payload_json", sa.JSON, nullable=True),
        ),
    )
    ensure_index("ix_events_entity", "events", ["entity_type", "entity_id"])
    ensure_index("ix_events_type", "events", ["event_type"])

    ensure_table(
        "quotes",
        lambda: op.create_table(
            "quotes",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("funding_source_id", sa.Integer, sa.ForeignKey("funding_sources.id"), nullable=True),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id"), nullable=True),
            sa.Column("quote_number", sa.String(length=64), nullable=True),
            sa.Column("issued_date", sa.Date, nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("fx_rate_to_usd", sa.Numeric(18, 8), nullable=False, server_default="1.0"),
            sa.Column("total_amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("amount_usd", sa.Numeric(18, 6), nullable=True),
            sa.Column("memo", sa.Text, nullable=True),
        ),
    )

    ensure_table(
        "quote_lines",
        lambda: op.create_table(
            "quote_lines",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("quote_id", sa.Integer, sa.ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("unit_cost", sa.Numeric(18, 6), nullable=True),
            sa.Column("amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
            sa.Column("expected_date", sa.Date, nullable=True),
        ),
    )

    ensure_table(
        "purchase_orders",
        lambda: op.create_table(
            "purchase_orders",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("funding_source_id", sa.Integer, sa.ForeignKey("funding_sources.id"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id"), nullable=True),
            sa.Column("po_number", sa.String(length=64), nullable=False, unique=True),
            sa.Column("ordered_date", sa.Date, nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("fx_rate_to_usd", sa.Numeric(18, 8), nullable=False, server_default="1.0"),
            sa.Column("total_amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("amount_usd", sa.Numeric(18, 6), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
            sa.Column("memo", sa.Text, nullable=True),
        ),
    )
    ensure_index("ix_purchase_orders_number", "purchase_orders", ["po_number"], unique=True)

    ensure_table(
        "po_lines",
        lambda: op.create_table(
            "po_lines",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("purchase_order_id", sa.Integer, sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("quote_line_id", sa.Integer, sa.ForeignKey("quote_lines.id"), nullable=True),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("unit_price", sa.Numeric(18, 6), nullable=True),
            sa.Column("amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
            sa.Column("deliverable_desc", sa.Text, nullable=True),
        ),
    )

    ensure_table(
        "invoices",
        lambda: op.create_table(
            "invoices",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("purchase_order_id", sa.Integer, sa.ForeignKey("purchase_orders.id"), nullable=True),
            sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id"), nullable=True),
            sa.Column("invoice_number", sa.String(length=64), nullable=False),
            sa.Column("invoice_date", sa.Date, nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("fx_rate_to_usd", sa.Numeric(18, 8), nullable=False, server_default="1.0"),
            sa.Column("total_amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("amount_usd", sa.Numeric(18, 6), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
            sa.Column("memo", sa.Text, nullable=True),
        ),
    )
    ensure_index("ix_invoices_number", "invoices", ["invoice_number"], unique=True)

    ensure_table(
        "invoice_lines",
        lambda: op.create_table(
            "invoice_lines",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
            sa.Column("po_line_id", sa.Integer, sa.ForeignKey("po_lines.id"), nullable=True),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("unit_price", sa.Numeric(18, 6), nullable=True),
            sa.Column("amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
        ),
    )

    ensure_table(
        "po_line_quote_line",
        lambda: op.create_table(
            "po_line_quote_line",
            sa.Column("po_line_id", sa.Integer, sa.ForeignKey("po_lines.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("quote_line_id", sa.Integer, sa.ForeignKey("quote_lines.id", ondelete="CASCADE"), primary_key=True),
        ),
    )

    ensure_table(
        "checkpoint_types",
        lambda: op.create_table(
            "checkpoint_types",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(length=50), nullable=False, unique=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
        ),
    )

    ensure_table(
        "fulfillment_lots",
        lambda: op.create_table(
            "fulfillment_lots",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("po_line_id", sa.Integer, sa.ForeignKey("po_lines.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lot_qty", sa.Numeric(18, 4), nullable=False),
            sa.Column("lot_identifier", sa.String(length=100), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
        ),
    )

    ensure_table(
        "milestone_instances",
        lambda: op.create_table(
            "milestone_instances",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("fulfillment_lot_id", sa.Integer, sa.ForeignKey("fulfillment_lots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("checkpoint_type_id", sa.Integer, sa.ForeignKey("checkpoint_types.id"), nullable=False),
            sa.Column("planned_date", sa.Date, nullable=True),
            sa.Column("actual_date", sa.Date, nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        ),
    )
    ensure_index("ix_milestone_instances_status", "milestone_instances", ["status"])

    ensure_table(
        "payment_schedules",
        lambda: op.create_table(
            "payment_schedules",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("purchase_order_id", sa.Integer, sa.ForeignKey("purchase_orders.id"), nullable=True),
            sa.Column("invoice_id", sa.Integer, sa.ForeignKey("invoices.id"), nullable=True),
            sa.Column("percent", sa.Numeric(6, 3), nullable=True),
            sa.Column("amount", sa.Numeric(18, 6), nullable=True),
            sa.Column("due_date_rule", payment_due_rule, nullable=False, server_default="NET_N"),
            sa.Column("net_days", sa.Integer, nullable=True),
            sa.Column("event_type", sa.String(length=50), nullable=True),
            sa.Column("due_date", sa.Date, nullable=True),
            sa.Column("status", payment_status, nullable=False, server_default="PLANNED"),
            sa.Column("paid_transaction_id", sa.String(length=36), sa.ForeignKey("transactions.id"), nullable=True),
        ),
    )
    ensure_index("ix_payment_schedule_due", "payment_schedules", ["due_date"])

    ensure_table(
        "fx_rates",
        lambda: op.create_table(
            "fx_rates",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("base_currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("quote_currency", sa.String(length=3), nullable=False),
            sa.Column("valid_from", sa.Date, nullable=False),
            sa.Column("valid_to", sa.Date, nullable=True),
            sa.Column("rate", sa.Numeric(18, 8), nullable=False),
            sa.Column("manual_override", sa.Boolean, nullable=False, server_default=sa.false()),
            mysql_engine="InnoDB",
        ),
    )
    ensure_index("ix_fx_rates_currency", "fx_rates", ["quote_currency", "valid_from"])

    ensure_table(
        "report_definitions",
        lambda: op.create_table(
            "report_definitions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("owner", sa.String(length=100), nullable=False),
            sa.Column("json_config", sa.JSON, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        ),
    )

    # Compatibility view for legacy portfolio endpoints
    conn.execute(text("DROP VIEW IF EXISTS v_portfolios"))
    conn.execute(text("DROP VIEW IF EXISTS portfolios_view"))

    for name, sql in VIEW_DEFINITIONS.items():
        conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
        conn.execute(text(sql))

    # schema version tracker
    if not inspector.has_table("schema_versions"):
        op.create_table(
            "schema_versions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("schema_version", sa.String(length=50), nullable=False),
            sa.Column("applied_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )
    conn.execute(text("INSERT INTO schema_versions(schema_version, applied_at) VALUES (:v, CURRENT_TIMESTAMP)"), {"v": "20230915_01"})


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if inspector.has_table("schema_versions"):
        conn.execute(text("DELETE FROM schema_versions WHERE schema_version = :v"), {"v": "20230915_01"})

    conn.execute(text("DROP TRIGGER IF EXISTS trg_portfolios_ai"))
    conn.execute(text("DROP TRIGGER IF EXISTS trg_portfolios_au"))
    conn.execute(text("DROP TRIGGER IF EXISTS trg_portfolios_ad"))

    op.drop_table("report_definitions")
    op.drop_index("ix_fx_rates_currency", table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_index("ix_payment_schedule_due", table_name="payment_schedules")
    op.drop_table("payment_schedules")
    op.drop_index("ix_milestone_instances_status", table_name="milestone_instances")
    op.drop_table("milestone_instances")
    op.drop_table("fulfillment_lots")
    op.drop_table("checkpoint_types")
    op.drop_table("po_line_quote_line")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_number", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("po_lines")
    op.drop_index("ix_purchase_orders_number", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.drop_table("quote_lines")
    op.drop_table("quotes")
    op.drop_index("ix_events_type", table_name="events")
    op.drop_index("ix_events_entity", table_name="events")
    op.drop_table("events")
    op.drop_table("transaction_deliverables")
    op.drop_table("transaction_invoice_lines")
    op.drop_table("transaction_po_lines")
    op.drop_index("ix_transactions_funding_source", table_name="transactions")
    op.drop_index("ix_transactions_date", table_name="transactions")
    op.drop_index("ix_transactions_state", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_funding_sources_closure", table_name="funding_sources")
    op.drop_index("ix_funding_sources_type", table_name="funding_sources")
    op.drop_table("funding_sources")

    if "portfolios" in inspector.get_table_names():
        existing_cols = {col["name"] for col in inspector.get_columns("portfolios")}
        for col in ["is_temporary", "closure_date", "cc_code", "car_code", "type"]:
            if col in existing_cols:
                op.drop_column("portfolios", col)

    funding_source_type.drop(op.get_bind(), checkfirst=False)
    transaction_state.drop(op.get_bind(), checkfirst=False)
    transaction_source_type.drop(op.get_bind(), checkfirst=False)
    payment_due_rule.drop(op.get_bind(), checkfirst=False)
    payment_status.drop(op.get_bind(), checkfirst=False)
