from pathlib import Path
from datetime import date as DateType
from decimal import Decimal
import os, time, types
from typing import List, Optional
from fastapi import BackgroundTasks
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, case
from .db import Base, engine, get_db
from . import models, schemas, models_finance  # noqa: F401 - ensure models are registered
from .routes_finance import router as finance_router
from .csv_io import export_to_csv, import_latest_csv
from .sql.views import ensure_views

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(finance_router)

def _shutdown():
    # slight delay so the HTTP response returns cleanly
    time.sleep(0.15)
    os._exit(0)

@app.post("/api/quit")
def quit_app(background_tasks: BackgroundTasks):
    background_tasks.add_task(_shutdown)
    return {"ok": True}


# --- Create tables (dev) ---
Base.metadata.create_all(bind=engine)
ensure_views(engine)

# --- Utility ---
def get_or_404(db, model, obj_id: int):
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(404, f"{model.__name__} {obj_id} not found")
    return obj

JOURNAL_KINDS = {"REALLOC", "ADJUST", "CORRECTION"}
ZERO_TOLERANCE = Decimal('0.000001')


def _serialize_journal(entry: models.JournalEntry) -> schemas.JournalEntryOut:
    postings = [
        schemas.JournalPostingOut(
            id=p.id,
            journal_id=p.journal_id,
            allocation_id=p.allocation_id,
            budget_id=p.budget_id,
            item_project_id=p.item_project_id,
            category_id=p.category_id,
            amount=float(p.amount),
            currency=p.currency,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in entry.postings
    ]
    return schemas.JournalEntryOut(
        id=entry.id,
        kind=entry.kind,
        posted_at=entry.posted_at.isoformat() if entry.posted_at else None,
        note=entry.note,
        created_by=entry.created_by,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
        net_amount=float(entry.net_amount),
        balanced=entry.balanced,
        postings=postings,
    )


def _prepare_journal_postings(db: Session, postings: List[schemas.JournalPostingIn]):
    if not postings:
        raise HTTPException(422, "at least one posting required")
    rows = []
    total = Decimal('0')
    for posting in postings:
        amount = Decimal(str(posting.amount))
        if amount == 0:
            raise HTTPException(422, "posting amount cannot be zero")
        currency = (posting.currency or "USD").upper()
        if posting.allocation_id:
            if any(v is not None for v in (posting.budget_id, posting.item_project_id, posting.category_id)):
                raise HTTPException(422, "allocation postings cannot specify budget/item/category")
            alloc = get_or_404(db, models.Allocation, posting.allocation_id)
            rows.append({
                "allocation_id": alloc.id,
                "budget_id": None,
                "item_project_id": None,
                "category_id": None,
                "amount": amount,
                "currency": currency,
            })
        else:
            if not (posting.budget_id and posting.item_project_id and posting.category_id):
                raise HTTPException(422, "budget_id, item_project_id, category_id required when allocation_id is null")
            category = get_or_404(db, models.Category, posting.category_id)
            if category.budget_id != posting.budget_id or category.item_project_id != posting.item_project_id:
                raise HTTPException(422, "category does not match provided budget/item_project")
            rows.append({
                "allocation_id": None,
                "budget_id": posting.budget_id,
                "item_project_id": posting.item_project_id,
                "category_id": posting.category_id,
                "amount": amount,
                "currency": currency,
            })
        total += amount
    if abs(total) > ZERO_TOLERANCE:
        raise HTTPException(422, "journal postings must net to zero")
    return rows

def _create_journal(
    db: Session,
    *,
    kind: str,
    note: Optional[str],
    created_by: Optional[str],
    postings: List[schemas.JournalPostingIn],
) -> models.JournalEntry:
    kind_upper = kind.upper()
    if kind_upper not in JOURNAL_KINDS:
        raise HTTPException(422, "invalid journal kind")
    rows = _prepare_journal_postings(db, postings)
    entry = models.JournalEntry(kind=kind_upper, note=note, created_by=created_by)
    db.add(entry)
    db.flush()
    for row in rows:
        db.add(
            models.JournalPosting(
                journal_id=entry.id,
                allocation_id=row['allocation_id'],
                budget_id=row['budget_id'],
                item_project_id=row['item_project_id'],
                category_id=row['category_id'],
                amount=row['amount'],
                currency=row['currency'],
            )
        )
    db.commit()
    entry = db.get(models.JournalEntry, entry.id)
    entry.postings  # evaluate relationship
    return entry

# --- CSV Snapshots ---
@app.post("/api/load-latest")
def load_latest(db: Session = Depends(get_db)):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    folder = import_latest_csv(db)
    return {"loaded_from": folder}

@app.post("/api/save-snapshot")
def save_snapshot(db: Session = Depends(get_db)):
    folder = export_to_csv(db)
    return {"saved_to": folder}

@app.get("/api/ping")
def ping():
    return {"ok": True}

# --- Portfolios ---
@app.get("/api/portfolios")
def list_portfolios(db: Session = Depends(get_db)):
    return db.execute(select(models.Portfolio)).scalars().all()

@app.post("/api/portfolios")
def create_portfolio(portfolio: schemas.PortfolioIn, db: Session = Depends(get_db)):
    payload = portfolio.model_dump()
    if payload.get("closure_date"):
        payload["closure_date"] = DateType.fromisoformat(payload["closure_date"])
    m = models.Portfolio(**payload)
    db.add(m); db.commit(); db.refresh(m)
    return m

@app.put("/api/portfolios/{portfolio_id}")
def update_portfolio(portfolio_id: int, portfolio: schemas.PortfolioIn, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Portfolio, portfolio_id)
    for k, v in portfolio.model_dump().items():
        if k == "closure_date" and v:
            v = DateType.fromisoformat(v)
        setattr(m, k, v)
    db.commit(); db.refresh(m)
    return m

@app.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Portfolio, portfolio_id)
    db.delete(m); db.commit()
    return {"ok": True}

# --- Project Groups ---
@app.get("/api/project-groups")
def list_pgs(db: Session = Depends(get_db)):
    return db.execute(select(models.ProjectGroup)).scalars().all()

@app.post("/api/project-groups")
def create_pg(pg: schemas.ProjectGroupIn, db: Session = Depends(get_db)):
    m = models.ProjectGroup(**pg.model_dump())
    db.add(m); db.commit(); db.refresh(m)
    return m

# --- Projects ---
@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    return db.execute(select(models.Project)).scalars().all()

@app.post("/api/projects")
def create_project(p: schemas.ProjectIn, db: Session = Depends(get_db)):
    data = p.model_dump()
    budget_id = data.get("budget_id")
    if not budget_id:
        budget_id = data.get("portfolio_id")
    if not budget_id:
        raise HTTPException(400, "budget_id or portfolio_id required")
    data["budget_id"] = budget_id
    data.setdefault("legacy_portfolio_id", data.get("portfolio_id"))
    m = models.Project(**data)
    db.add(m); db.commit(); db.refresh(m)
    return m

@app.put("/api/projects/{pid}")
def update_project(pid: int, p: schemas.ProjectIn, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Project, pid)
    data = p.model_dump()
    budget_id = data.get("budget_id")
    if not budget_id and data.get("portfolio_id"):
        budget_id = data["portfolio_id"]
    if budget_id:
        data["budget_id"] = budget_id
    data.setdefault("legacy_portfolio_id", data.get("portfolio_id", m.legacy_portfolio_id))
    for k, v in data.items():
        if v is not None or k in {"description", "code", "line"}:
            setattr(m, k, v)
    db.commit(); db.refresh(m)
    return m

@app.delete("/api/projects/{pid}")
def delete_project(pid: int, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Project, pid)
    db.delete(m); db.commit()
    return {"ok": True}

# --- Vendors ---
@app.get("/api/vendors")
def list_vendors(db: Session = Depends(get_db)):
    return db.execute(select(models.Vendor)).scalars().all()

@app.post("/api/vendors")
def create_vendor(v: schemas.VendorIn, db: Session = Depends(get_db)):
    m = models.Vendor(**v.model_dump())
    db.add(m); db.commit(); db.refresh(m)
    return m

@app.put("/api/vendors/{vid}")
def update_vendor(vid: int, v: schemas.VendorIn, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Vendor, vid)
    for k, v2 in v.model_dump().items(): setattr(m, k, v2)
    db.commit(); db.refresh(m)
    return m

@app.delete("/api/vendors/{vid}")
def delete_vendor(vid: int, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Vendor, vid)
    db.delete(m); db.commit()
    return {"ok": True}

# --- Categories (n-level) ---
@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)):
    return db.execute(select(models.Category)).scalars().all()

@app.post("/api/categories")
def create_category(c: schemas.CategoryIn, db: Session = Depends(get_db)):
    data = c.model_dump()
    item_project_id = data.get("item_project_id") or data.get("project_id")
    if not item_project_id:
        raise HTTPException(400, "item_project_id or project_id is required")
    project = get_or_404(db, models.Project, item_project_id)
    data["item_project_id"] = item_project_id
    data["budget_id"] = data.get("budget_id") or project.budget_id
    if data.get("amount_leaf") is not None:
        data["amount_leaf"] = float(data["amount_leaf"])
    m = models.Category(**data)
    db.add(m); db.commit(); db.refresh(m)
    return m

@app.put("/api/categories/{cid}")
def update_category(cid: int, c: schemas.CategoryIn, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Category, cid)
    data = c.model_dump()
    item_project_id = data.get("item_project_id") or data.get("project_id") or m.item_project_id
    project = get_or_404(db, models.Project, item_project_id)
    data["item_project_id"] = item_project_id
    data["budget_id"] = data.get("budget_id") or project.budget_id
    if data.get("amount_leaf") is not None:
        data["amount_leaf"] = float(data["amount_leaf"])
    for k, v in data.items():
        setattr(m, k, v)
    db.commit(); db.refresh(m)
    return m

@app.delete("/api/categories/{cid}")
def delete_category(cid: int, db: Session = Depends(get_db)):
    m = get_or_404(db, models.Category, cid)
    db.delete(m); db.commit()
    return {"ok": True}

@app.get("/api/categories/tree")
def category_tree(db: Session = Depends(get_db)):
    rows = db.execute(select(models.Category)).scalars().all()
    by_id = {c.id: {"id": c.id, "name": c.name, "parent_id": c.parent_id, "project_id": c.project_id, "children": []} for c in rows}
    roots = []
    for c in rows:
        node = by_id[c.id]
        if c.parent_id and c.parent_id in by_id:
            by_id[c.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots

# --- Tags ---
@app.get("/api/tags")
def list_tags(db: Session = Depends(get_db)):
    return db.execute(select(models.Tag)).scalars().all()

@app.post("/api/tags")
def create_tag(tag: schemas.TagIn, db: Session = Depends(get_db)):
    name = tag.name.strip()
    if not name:
        raise HTTPException(400, "Tag name required")
    existing = db.execute(select(models.Tag).where(models.Tag.name == name)).scalar_one_or_none()
    if existing:
        return existing
    m = models.Tag(name=name)
    db.add(m); db.commit(); db.refresh(m)
    return m

# --- Entries + Allocations + Comments ---
@app.get("/api/entries")
def list_entries(db: Session = Depends(get_db)):
    return db.execute(select(models.Entry)).scalars().all()

@app.post("/api/entries")
def create_entry(e: schemas.EntryIn, db: Session = Depends(get_db)):
    payload = e.model_dump(exclude={"allocations", "tags"})
    if payload.get("date") is not None:
        try:
            payload["date"] = DateType.fromisoformat(payload["date"])
        except Exception:
            raise HTTPException(400, "date must be ISO format YYYY-MM-DD")

    m = models.Entry(**payload)
    db.add(m); db.flush()

    # Allocations must sum to entry amount (if present)
    if e.allocations:
        total = 0.0
        for a in e.allocations:
            db.add(models.Allocation(entry_id=m.id, portfolio_id=a.portfolio_id, amount=a.amount))
            total += a.amount
        if abs(total - e.amount) > 1e-6:
            raise HTTPException(400, "Allocations must sum to entry amount")

    # Tags (optional)
    if e.tags:
        for t in e.tags:
            tname = (t or "").strip()
            if not tname:
                continue
            tag = db.execute(select(models.Tag).where(models.Tag.name == tname)).scalar_one_or_none()
            if not tag:
                tag = models.Tag(name=tname)
                db.add(tag); db.flush()
            db.add(models.EntryTag(entry_id=m.id, tag_id=tag.id))

    db.commit(); db.refresh(m)
    return m

@app.put("/api/entries/{eid}")
def update_entry(eid: int, e: schemas.EntryIn, db: Session = Depends(get_db)):
    get_or_404(db, models.Entry, eid)
    raise HTTPException(409, "entries are append-only; use journals")

@app.delete("/api/entries/{eid}")
def delete_entry(eid: int, db: Session = Depends(get_db)):
    get_or_404(db, models.Entry, eid)
    raise HTTPException(409, "entries are append-only; use journals")

@app.get("/api/allocations")
def list_allocs(db: Session = Depends(get_db)):
    return db.execute(select(models.Allocation)).scalars().all()

@app.get("/api/comments")
def list_comments(db: Session = Depends(get_db)):
    return db.execute(select(models.Comment)).scalars().all()

@app.post("/api/comments")
def create_comment(c: schemas.CommentIn, db: Session = Depends(get_db)):
    m = models.Comment(**c.model_dump())
    db.add(m); db.commit(); db.refresh(m)
    return m

@app.put("/api/project-groups/{pg_id}", response_model=schemas.ProjectGroupOut)
def update_project_group(pg_id: int, data: schemas.ProjectGroupIn, db: Session = Depends(get_db)):
    pg = db.get(models.ProjectGroup, pg_id)
    if not pg:
        raise HTTPException(status_code=404, detail="Not found")
    # update fields (treat empty strings as None where useful)
    pg.code = (data.code or None)
    pg.name = data.name
    pg.description = (data.description or None)
    db.commit()
    db.refresh(pg)
    return pg

@app.delete("/api/project-groups/{pg_id}")
def delete_project_group(pg_id: int, db: Session = Depends(get_db)):
    pg = db.get(models.ProjectGroup, pg_id)
    if not pg:
        return {"ok": True}
    db.delete(pg)
    db.commit()
    return {"ok": True}

# --- Pivots: generic summary (unchanged) ---
@app.post("/api/journals", response_model=schemas.JournalEntryOut)
def create_journal_entry(payload: schemas.JournalEntryIn, db: Session = Depends(get_db)):
    entry = _create_journal(
        db,
        kind=payload.kind,
        note=payload.note,
        created_by=payload.created_by,
        postings=payload.postings,
    )
    return _serialize_journal(entry)


@app.get("/api/journals/{journal_id}", response_model=schemas.JournalEntryOut)
def get_journal(journal_id: int, db: Session = Depends(get_db)):
    entry = get_or_404(db, models.JournalEntry, journal_id)
    entry.postings
    return _serialize_journal(entry)


@app.get("/api/journals", response_model=List[schemas.JournalEntryOut])
def list_journals(
    kind: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(models.JournalEntry)
    if kind:
        stmt = stmt.where(models.JournalEntry.kind == kind.upper())
    stmt = stmt.order_by(models.JournalEntry.posted_at.desc(), models.JournalEntry.id.desc()).limit(limit)
    entries = db.execute(stmt).scalars().all()
    return [_serialize_journal(entry) for entry in entries]


@app.post("/api/journals/reallocate", response_model=schemas.JournalEntryOut)
def journal_reallocate(payload: schemas.JournalReallocateIn, db: Session = Depends(get_db)):
    amount = Decimal(str(payload.amount))
    if amount <= 0:
        raise HTTPException(422, "amount must be positive")
    from_alloc = get_or_404(db, models.Allocation, payload.from_allocation_id)
    to_alloc = get_or_404(db, models.Allocation, payload.to_allocation_id)
    postings = [
        schemas.JournalPostingIn(allocation_id=from_alloc.id, amount=float(-amount), currency="USD"),
        schemas.JournalPostingIn(allocation_id=to_alloc.id, amount=float(amount), currency="USD"),
    ]
    entry = _create_journal(
        db,
        kind="REALLOC",
        note=payload.note,
        created_by=payload.created_by,
        postings=postings,
    )
    return _serialize_journal(entry)


@app.post("/api/journals/adjust", response_model=schemas.JournalEntryOut)
def journal_adjust(payload: schemas.JournalAdjustIn, db: Session = Depends(get_db)):
    entry = _create_journal(
        db,
        kind="ADJUST",
        note=payload.note,
        created_by=payload.created_by,
        postings=payload.postings,
    )
    return _serialize_journal(entry)


@app.get("/api/pivot/summary")
def pivot_summary(
    by: Optional[str] = None,
    scenario: str = "actual",  # actual | ideal
    portfolio_id: Optional[int] = None,
    project_id: Optional[int] = None,
    group_id: Optional[int] = None,
    category_id: Optional[int] = None,
    vendor_id: Optional[int] = None,
    kind: Optional[str] = None,
    db: Session = Depends(get_db)
):
    eff_portfolio = case(
        (and_(models.Entry.mischarged == True, models.Entry.intended_portfolio_id.is_not(None)), models.Entry.intended_portfolio_id),
        else_=models.Entry.portfolio_id
    )

    # choose portfolio column based on scenario
    portfolio_col = eff_portfolio if scenario == "ideal" else models.Entry.portfolio_id

    base_cols = [
        portfolio_col.label("portfolio_id"),
        models.Entry.project_id,
        models.Entry.category_id,
        models.Entry.vendor_id,
        models.Entry.kind,
        func.sum(models.Entry.amount).label("total"),
    ]
    stmt = select(*base_cols)

    # join for group if needed
    if by == "group" or group_id is not None:
        stmt = stmt.join(models.Project, models.Project.id == models.Entry.project_id, isouter=True)
        stmt = stmt.add_columns(models.Project.group_id)

    # filters (respect scenario for portfolio_id)
    conds = []
    if portfolio_id is not None:
        conds.append(portfolio_col == portfolio_id)
    if project_id is not None:
        conds.append(models.Entry.project_id == project_id)
    if category_id is not None:
        conds.append(models.Entry.category_id == category_id)
    if vendor_id is not None:
        conds.append(models.Entry.vendor_id == vendor_id)
    if kind is not None:
        conds.append(models.Entry.kind == kind)
    if group_id is not None:
        stmt = stmt.where(models.Project.group_id == group_id)
    if conds: stmt = stmt.where(and_(*conds))

    # group by
    if by == "portfolio":
        stmt = stmt.group_by(portfolio_col)
    elif by == "project":
        stmt = stmt.group_by(models.Entry.project_id)
    elif by == "group":
        stmt = stmt.group_by(models.Project.group_id)
    elif by == "category":
        stmt = stmt.group_by(models.Entry.category_id)
    elif by == "vendor":
        stmt = stmt.group_by(models.Entry.vendor_id)
    elif by == "kind":
        stmt = stmt.group_by(models.Entry.kind)
    else:
        stmt = stmt.group_by(portfolio_col, models.Entry.project_id, models.Entry.category_id, models.Entry.vendor_id, models.Entry.kind)

    rows = db.execute(stmt).all()
    return [dict(r._mapping) for r in rows]

@app.get("/api/status/health")
def health(
    level: str,                     # 'portfolio' or 'category'
    scenario: str = "actual",       # 'actual' or 'ideal'
    portfolio_id: Optional[int] = None,      # required for level='category'
    db: Session = Depends(get_db)
):
    """
    Compute budget vs actual with status colors:
      - green: actual <= budget
      - yellow: 0% < overrun <= 10%
      - red: overrun > 10%  (or budget==0 and actual>0)
    'actual' kinds: po, unplanned, adjustment
    """
    if level not in {"portfolio", "category"}:
        raise HTTPException(400, "level must be 'portfolio' or 'category'")

    eff_portfolio = case(
        (and_(models.Entry.mischarged == True, models.Entry.intended_portfolio_id.is_not(None)), models.Entry.intended_portfolio_id),
        else_=models.Entry.portfolio_id
    )
    portfolio_col = eff_portfolio if scenario == "ideal" else models.Entry.portfolio_id

    keys = [portfolio_col.label("portfolio_id")] if level == "portfolio" else [portfolio_col.label("portfolio_id"), models.Entry.category_id]
    if level == "category":
        if portfolio_id is None:
            raise HTTPException(400, "portfolio_id required when level='category' ")
    # budget
    bq = select(*keys, func.sum(models.Entry.amount).label("budget")).where(models.Entry.kind == "budget")
    if level == "category": bq = bq.where(portfolio_col == portfolio_id)
    bq = bq.group_by(*keys)
    b_rows = db.execute(bq).all()

    # actual
    actual_kinds = ("po", "unplanned", "adjustment")
    aq = select(*keys, func.sum(models.Entry.amount).label("actual")).where(models.Entry.kind.in_(actual_kinds))
    if level == "category": aq = aq.where(portfolio_col == portfolio_id)
    aq = aq.group_by(*keys)
    a_rows = db.execute(aq).all()

    # merge in Python
    def key_of(row):
        if level == "portfolio":
            return (row._mapping["portfolio_id"],)
        return (row._mapping["portfolio_id"], row._mapping["category_id"])

    agg = {}
    for r in b_rows:
        k = key_of(r)
        agg[k] = {"portfolio_id": r._mapping["portfolio_id"], "budget": r._mapping["budget"]}
        if level == "category": agg[k]["category_id"] = r._mapping["category_id"]
    for r in a_rows:
        k = key_of(r)
        if k not in agg:
            agg[k] = {"portfolio_id": r._mapping["portfolio_id"], "budget": 0.0}
            if level == "category": agg[k]["category_id"] = r._mapping["category_id"]
        agg[k]["actual"] = r._mapping["actual"]

    # finalize, compute status
    out = []
    for v in agg.values():
        budget = float(v.get("budget") or 0.0)
        actual = float(v.get("actual") or 0.0)
        over = actual - budget
        if budget <= 0:
            variance_pct = None if actual == 0 else 1.0
        else:
            variance_pct = over / budget
        if budget == 0 and actual > 0:
            status = "red"
        elif actual <= budget:
            status = "green"
        elif variance_pct is not None and variance_pct <= 0.10:
            status = "yellow"
        else:
            status = "red"
        v.update({"variance_pct": variance_pct, "status": status})
        out.append(v)
    return out

# --- Mount frontend (LAST) ---


class No304StaticFiles(StaticFiles):
    """Static files handler that always re-serves assets instead of returning 304."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        if hasattr(response, "is_not_modified"):
            response.is_not_modified = types.MethodType(lambda self, headers: False, response)
        if hasattr(response, "headers"):
            headers = response.headers
            headers["Cache-Control"] = "no-store"
            for header_name in ("etag", "last-modified"):
                if header_name in headers:
                    del headers[header_name]
        return response


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", No304StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
