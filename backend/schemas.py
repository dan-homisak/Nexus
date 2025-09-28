from typing import Optional, List
from pydantic import BaseModel, ConfigDict

# ---- Portfolios ----
class PortfolioIn(BaseModel):
    name: str
    fiscal_year: Optional[str] = None
    owner: Optional[str] = None
    type: Optional[str] = "COST_CENTER"
    car_code: Optional[str] = None
    cc_code: Optional[str] = None
    closure_date: Optional[str] = None
    is_temporary: Optional[bool] = False

class PortfolioOut(PortfolioIn):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ---- Project Groups ----
class ProjectGroupIn(BaseModel):
    code: Optional[str] = None
    name: str
    description: Optional[str] = None

class ProjectGroupOut(ProjectGroupIn):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ---- Projects ----
class ProjectIn(BaseModel):
    portfolio_id: int
    name: str
    group_id: Optional[int] = None
    code: Optional[str] = None
    line: Optional[str] = None
    budget_id: Optional[int] = None
    description: Optional[str] = None
    legacy_portfolio_id: Optional[int] = None

class ProjectOut(ProjectIn):
    id: int
    class Config:
        from_attributes = True

# ---- Categories (n-level) ----
class CategoryIn(BaseModel):
    name: str
    parent_id: Optional[int] = None
    project_id: Optional[int] = None  # legacy field
    item_project_id: Optional[int] = None
    budget_id: Optional[int] = None
    description: Optional[str] = None
    amount_leaf: Optional[float] = None
    is_leaf: Optional[bool] = None

class CategoryOut(CategoryIn):
    id: int
    class Config:
        from_attributes = True

# ---- Vendors ----
class VendorIn(BaseModel):
    name: str

class VendorOut(VendorIn):
    id: int
    class Config:
        from_attributes = True

# ---- Allocations ----
class AllocationIn(BaseModel):
    portfolio_id: int
    amount: float

# ---- Tags ----
class TagIn(BaseModel):
    name: str

class TagOut(TagIn):
    id: int
    class Config:
        from_attributes = True

class EntryIn(BaseModel):
    date: Optional[str] = None
    kind: str
    amount: float
    description: Optional[str] = None
    portfolio_id: int
    project_id: Optional[int] = None
    item_project_id: Optional[int] = None
    category_id: Optional[int] = None
    vendor_id: Optional[int] = None
    po_number: Optional[str] = None
    quote_ref: Optional[str] = None
    allocations: Optional[List[AllocationIn]] = None
    tags: Optional[List[str]] = None
    # NEW
    mischarged: Optional[bool] = False
    intended_portfolio_id: Optional[int] = None


class EntryOut(EntryIn):
    id: int
    class Config:
        from_attributes = True

# ---- Comments ----
class CommentIn(BaseModel):
    entry_id: int
    field: Optional[str] = None
    text: str
    created_at: str

class CommentOut(CommentIn):
    id: int
    class Config:
        from_attributes = True
