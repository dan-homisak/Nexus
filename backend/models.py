from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class Portfolio(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    fiscal_year = Column(String)
    owner = Column(String)
    type = Column(String, default="COST_CENTER")
    car_code = Column(String)
    cc_code = Column(String)
    closure_date = Column(Date)
    is_temporary = Column(Boolean, default=False)
    projects = relationship("Project", back_populates="portfolio", cascade="all, delete")


class ProjectGroup(Base):
    __tablename__ = "project_groups"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)
    name = Column(String, nullable=False)
    description = Column(Text)


class Project(Base):
    """Represents an item/project under a funding source."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    budget_id = Column(Integer, ForeignKey("funding_sources.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey("project_groups.id"))
    code = Column(String)
    line = Column(String)
    description = Column(Text)
    legacy_portfolio_id = Column(Integer)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    portfolio = relationship("Portfolio", back_populates="projects")
    group = relationship("ProjectGroup")
    line_assets = relationship(
        "LineAsset",
        secondary="item_project_line_assets",
        back_populates="item_projects",
    )
    allocations = relationship("Allocation", back_populates="item_project")


class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class LineAsset(Base):
    __tablename__ = "line_assets"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    item_projects = relationship(
        "Project",
        secondary="item_project_line_assets",
        back_populates="line_assets",
    )


class ItemProjectLineAsset(Base):
    __tablename__ = "item_project_line_assets"
    item_project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    line_asset_id = Column(
        Integer,
        ForeignKey("line_assets.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)


class Category(Base):
    """N-level category tree scoped to a single item/project."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("name", "parent_id", "project_id", name="uq_cat_sibling_scope"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    budget_id = Column(Integer, ForeignKey("funding_sources.id", ondelete="CASCADE"), nullable=False)
    item_project_id = Column(
        "project_id",
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    description = Column(Text)
    is_leaf = Column(Boolean, nullable=False, default=True)
    amount_leaf = Column(Numeric(18, 2))
    rollup_amount = Column(Numeric(18, 2))
    path_ids = Column(JSON)
    path_names = Column(JSON)
    path_depth = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    parent = relationship("Category", remote_side=[id], backref="children")
    item_project = relationship("Project")
    allocations = relationship("Allocation", back_populates="category")

    @property
    def project_id(self) -> int:
        return self.item_project_id

    @project_id.setter
    def project_id(self, value: int) -> None:
        self.item_project_id = value


class Entry(Base):
    __tablename__ = "entries"
    id = Column(Integer, primary_key=True)
    date = Column(Date)
    kind = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text)

    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    item_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)

    po_number = Column(String)
    quote_ref = Column(String)

    mischarged = Column(Boolean, nullable=False, default=False)
    intended_portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=True)

    allocations = relationship("Allocation", back_populates="entry", cascade="all, delete-orphan")


class Allocation(Base):
    __tablename__ = "allocations"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    item_project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    budget_id = Column(Integer, ForeignKey("funding_sources.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(10), nullable=False, server_default="USD")
    posted_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    entry = relationship("Entry", back_populates="allocations")
    category = relationship("Category", back_populates="allocations")
    item_project = relationship("Project", back_populates="allocations")
    postings = relationship(
        "JournalPosting",
        back_populates="allocation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @hybrid_property
    def adjustment_delta(self):
        return sum(p.amount for p in self.postings) if self.postings else 0

    @adjustment_delta.expression
    def adjustment_delta(cls):
        return (
            select(func.coalesce(func.sum(JournalPosting.amount), 0))
            .where(JournalPosting.allocation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def effective_amount(self):
        return (self.amount or 0) + self.adjustment_delta

    @effective_amount.expression
    def effective_amount(cls):
        return cls.amount + cls.adjustment_delta


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('REALLOC','ADJUST','CORRECTION')", name="ck_journal_entries_kind"),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False)
    posted_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    note = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    postings = relationship("JournalPosting", back_populates="journal_entry", cascade="all, delete-orphan")

    @hybrid_property
    def net_amount(self):
        return sum(p.amount for p in self.postings) if self.postings else 0

    @net_amount.expression
    def net_amount(cls):
        return (
            select(func.coalesce(func.sum(JournalPosting.amount), 0))
            .where(JournalPosting.journal_id == cls.id)
            .scalar_subquery()
        )

    @property
    def balanced(self) -> bool:
        return abs(float(self.net_amount)) < 1e-6


class JournalPosting(Base):
    __tablename__ = "journal_postings"
    __table_args__ = (
        CheckConstraint(
            "(allocation_id IS NOT NULL AND budget_id IS NULL AND item_project_id IS NULL AND category_id IS NULL)"
            " OR (allocation_id IS NULL AND budget_id IS NOT NULL AND item_project_id IS NOT NULL AND category_id IS NOT NULL)",
            name="ck_journal_postings_target",
        ),
    )

    id = Column(Integer, primary_key=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False)
    allocation_id = Column(Integer, ForeignKey("allocations.id", ondelete="SET NULL"), nullable=True)
    budget_id = Column(Integer, ForeignKey("funding_sources.id", ondelete="CASCADE"), nullable=True)
    item_project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(10), nullable=False, server_default="USD")
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    journal_entry = relationship("JournalEntry", back_populates="postings")
    allocation = relationship("Allocation", back_populates="postings")
    item_project = relationship("Project")
    category = relationship("Category")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    field = Column(String)
    text = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    color = Column(String)
    description = Column(Text)
    is_deprecated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class EntryTag(Base):
    __tablename__ = "entry_tags"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (UniqueConstraint("entry_id", "tag_id", name="uq_entry_tag"),)
