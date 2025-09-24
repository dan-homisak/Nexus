import pandas as pd
from pathlib import Path
from sqlalchemy.orm import Session
from . import models
from .util import latest_version_dir, new_version_dir

def export_to_csv(db: Session):
    outdir = new_version_dir()

    def dump(model, fname):
        df = pd.read_sql(db.query(model).statement, db.bind)
        df.to_csv(outdir / fname, index=False)

    dump(models.Portfolio, "portfolios.csv")
    dump(models.ProjectGroup, "project_groups.csv")
    dump(models.Project, "projects.csv")
    dump(models.Category, "categories.csv")
    dump(models.Vendor, "vendors.csv")
    dump(models.Entry, "entries.csv")
    dump(models.Allocation, "allocations.csv")
    dump(models.Comment, "comments.csv")
    dump(models.Tag, "tags.csv")
    dump(models.EntryTag, "entry_tags.csv")
    return str(outdir)

def import_latest_csv(db: Session):
    indir = latest_version_dir()
    if not indir:
        return None

    def maybe_read(name):
        p = indir / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    portfolios = maybe_read("portfolios.csv")
    pgs = maybe_read("project_groups.csv")
    projects = maybe_read("projects.csv")
    cats = maybe_read("categories.csv")
    vendors = maybe_read("vendors.csv")
    entries = maybe_read("entries.csv")
    allocs = maybe_read("allocations.csv")
    comments = maybe_read("comments.csv")
    tags = maybe_read("tags.csv")
    entry_tags = maybe_read("entry_tags.csv")

    if not portfolios.empty:
        db.bulk_insert_mappings(models.Portfolio, portfolios.to_dict(orient="records"))
    if not pgs.empty:
        db.bulk_insert_mappings(models.ProjectGroup, pgs.to_dict(orient="records"))
    if not projects.empty:
        db.bulk_insert_mappings(models.Project, projects.to_dict(orient="records"))
    if not cats.empty:
        db.bulk_insert_mappings(models.Category, cats.to_dict(orient="records"))
    if not vendors.empty:
        db.bulk_insert_mappings(models.Vendor, vendors.to_dict(orient="records"))
    if not entries.empty:
        db.bulk_insert_mappings(models.Entry, entries.to_dict(orient="records"))
    if not allocs.empty:
        db.bulk_insert_mappings(models.Allocation, allocs.to_dict(orient="records"))
    if not comments.empty:
        db.bulk_insert_mappings(models.Comment, comments.to_dict(orient="records"))
    if not tags.empty:
        db.bulk_insert_mappings(models.Tag, tags.to_dict(orient="records"))
    if not entry_tags.empty:
        db.bulk_insert_mappings(models.EntryTag, entry_tags.to_dict(orient="records"))

    db.commit()
    return str(indir)
