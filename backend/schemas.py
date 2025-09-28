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
    model_config = ConfigDict(from_attributes=True)

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
    model_config = ConfigDict(from_attributes=True)

# ---- Vendors ----
class VendorIn(BaseModel):
    name: str

class VendorOut(VendorIn):
    id: int
    model_config = ConfigDict(from_attributes=True)

# ---- Allocations ----
class AllocationIn(BaseModel):
    portfolio_id: int
    amount: float

# ---- Tags ----
class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None
    description: Optional[str] = None
    actor: Optional[str] = None


class TagUpdate(BaseModel):
    color: Optional[str] = None
    description: Optional[str] = None
    is_deprecated: Optional[bool] = None
    actor: Optional[str] = None


class TagRename(BaseModel):
    name: str
    actor: Optional[str] = None


class TagMerge(BaseModel):
    actor: Optional[str] = None


class TagOut(BaseModel):
    id: int
    name: str
    color: Optional[str] = None
    description: Optional[str] = None
    is_deprecated: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class TagAssignmentIn(BaseModel):
    tag_id: Optional[int] = None
    tag_name: Optional[str] = None
    entity_type: str
    entity_id: int
    scope: Optional[str] = None
    actor: Optional[str] = None


class TagAssignmentOut(BaseModel):
    id: int
    tag_id: int
    entity_type: str
    entity_id: int
    scope: Optional[str] = None
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class EffectiveTagOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    tag_id: int
    tag_name: str
    tag_color: Optional[str] = None
    scope: Optional[str] = None
    source: str
    path_ids: Optional[str] = None
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class BackgroundJobOut(BaseModel):
    id: int
    kind: str
    status: str
    payload: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class RebuildRequest(BaseModel):
    actor: Optional[str] = None


# ---- Journals ----
class JournalPostingIn(BaseModel):
    allocation_id: Optional[int] = None
    budget_id: Optional[int] = None
    item_project_id: Optional[int] = None
    category_id: Optional[int] = None
    amount: float
    currency: Optional[str] = "USD"


class JournalEntryIn(BaseModel):
    kind: str
    note: Optional[str] = None
    created_by: Optional[str] = None
    postings: List[JournalPostingIn]


class JournalPostingOut(JournalPostingIn):
    id: int
    journal_id: int
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class JournalEntryOut(BaseModel):
    id: int
    kind: str
    posted_at: Optional[str] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    net_amount: float
    balanced: bool
    postings: List[JournalPostingOut]
    model_config = ConfigDict(from_attributes=True)



class JournalReallocateIn(BaseModel):
    from_allocation_id: int
    to_allocation_id: int
    amount: float
    note: Optional[str] = None
    created_by: Optional[str] = None


class JournalAdjustIn(BaseModel):
    postings: List[JournalPostingIn]
    note: Optional[str] = None
    created_by: Optional[str] = None


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
    model_config = ConfigDict(from_attributes=True)

# ---- Comments ----
class CommentIn(BaseModel):
    entry_id: int
    field: Optional[str] = None
    text: str
    created_at: str

class CommentOut(CommentIn):
    id: int
    model_config = ConfigDict(from_attributes=True)
