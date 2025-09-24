from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, Text, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from .db import Base

class Car(Base):
    __tablename__ = "cars"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    fiscal_year = Column(String)
    owner = Column(String)
    projects = relationship("Project", back_populates="car", cascade="all, delete")

class ProjectGroup(Base):
    __tablename__ = "project_groups"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)   # optional short code
    name = Column(String, nullable=False)
    description = Column(Text)

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    car_id = Column(Integer, ForeignKey("cars.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey("project_groups.id"))
    code = Column(String)
    line = Column(String)

    car = relationship("Car", back_populates="projects")
    group = relationship("ProjectGroup")

class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class Category(Base):
    """
    N-level category tree. Optional scope by project (or leave NULL for global).
    """
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    parent = relationship("Category", remote_side=[id], backref="children")
    project = relationship("Project")

    __table_args__ = (
        UniqueConstraint("name", "parent_id", "project_id", name="uq_cat_sibling_scope"),
    )

class Entry(Base):
    __tablename__ = "entries"
    id = Column(Integer, primary_key=True)
    date = Column(Date)
    kind = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text)

    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)

    po_number = Column(String)
    quote_ref = Column(String)

    # NEW
    mischarged = Column(Boolean, nullable=False, default=False)
    intended_car_id = Column(Integer, ForeignKey("cars.id"), nullable=True)

class Allocation(Base):
    __tablename__ = "allocations"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    amount = Column(Float, nullable=False)

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    field = Column(String)   # e.g., "amount" or NULL for whole-entry
    text = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)  # ISO string

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class EntryTag(Base):
    __tablename__ = "entry_tags"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    __table_args__ = (UniqueConstraint("entry_id", "tag_id", name="uq_entry_tag"),)
