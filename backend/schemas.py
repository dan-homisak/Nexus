from typing import Optional, List
from pydantic import BaseModel, ConfigDict

# ---- Cars ----
class CarIn(BaseModel):
    name: str
    fiscal_year: Optional[str] = None
    owner: Optional[str] = None

class CarOut(CarIn):
    id: int
    class Config:
        from_attributes = True

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
    car_id: int
    name: str
    group_id: Optional[int] = None
    code: Optional[str] = None
    line: Optional[str] = None

class ProjectOut(ProjectIn):
    id: int
    class Config:
        from_attributes = True

# ---- Categories (n-level) ----
class CategoryIn(BaseModel):
    name: str
    parent_id: Optional[int] = None
    project_id: Optional[int] = None  # NULL => global category

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
    car_id: int
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
    car_id: int
    project_id: Optional[int] = None
    category_id: Optional[int] = None
    vendor_id: Optional[int] = None
    po_number: Optional[str] = None
    quote_ref: Optional[str] = None
    allocations: Optional[List[AllocationIn]] = None
    tags: Optional[List[str]] = None
    # NEW
    mischarged: Optional[bool] = False
    intended_car_id: Optional[int] = None


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
