"""Tag management service helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import distinct, func, select, text
from sqlalchemy.orm import Session

from .. import models, models_finance

VALID_ENTITY_TYPES = {
    "budget",
    "item_project",
    "category",
    "entry",
    "line_asset",
    "vendor",
}

ENTITY_MODEL_MAP = {
    "budget": models_finance.FundingSource,
    "item_project": models.Project,
    "category": models.Category,
    "entry": models.Entry,
    "line_asset": models.LineAsset,
    "vendor": models.Vendor,
}


_AUDIT_READY: Dict[int, bool] = {}
_TAGS_READY: Dict[int, bool] = {}


class TagServiceError(ValueError):
    """Domain-level validation error."""


def _normalize_tag_name(name: str) -> str:
    value = (name or "").strip().lower()
    if not value:
        raise TagServiceError("tag name is required")
    if " " in value:
        raise TagServiceError("tag names may not contain spaces")
    return value


def _normalize_scope(scope: Optional[str]) -> str:
    return (scope or "").strip()


def _ensure_audit_table(db: Session) -> bool:
    bind = db.get_bind()
    if bind is None:
        return False
    key = id(bind)
    ready = _AUDIT_READY.get(key)
    if ready:
        return True
    try:
        models.AuditEvent.__table__.create(bind, checkfirst=True)
    except Exception:  # pragma: no cover - legacy DB fallback
        _AUDIT_READY[key] = False
        return False
    _AUDIT_READY[key] = True
    return True


def _ensure_tags_table(db: Session) -> bool:
    bind = db.get_bind()
    if bind is None:
        return False
    key = id(bind)
    ready = _TAGS_READY.get(key)
    if ready:
        return True
    try:
        info = bind.execute(text("PRAGMA table_info(tags)")).fetchall()
    except Exception:  # pragma: no cover - surface as legacy fallback
        _TAGS_READY[key] = False
        return False
    columns = {row[1] for row in info}
    statements: List[str] = []
    if "color" not in columns:
        statements.append("ALTER TABLE tags ADD COLUMN color TEXT")
    if "description" not in columns:
        statements.append("ALTER TABLE tags ADD COLUMN description TEXT")
    if "is_deprecated" not in columns:
        statements.append("ALTER TABLE tags ADD COLUMN is_deprecated BOOLEAN NOT NULL DEFAULT 0")
    if "created_at" not in columns:
        statements.append("ALTER TABLE tags ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
    if "updated_at" not in columns:
        statements.append("ALTER TABLE tags ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
    for stmt in statements:
        bind.execute(text(stmt))
    if statements and "is_deprecated" not in columns:
        bind.execute(text("UPDATE tags SET is_deprecated = COALESCE(is_deprecated, 0)"))
    _TAGS_READY[key] = True
    return True


def _log_audit(
    db: Session,
    *,
    event_type: str,
    actor: Optional[str],
    description: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not _ensure_audit_table(db):
        return
    db.add(
        models.AuditEvent(
            event_type=event_type,
            actor=actor,
            description=description,
            payload=json.dumps(payload or {}),
        )
    )


def _ensure_entity_exists(db: Session, entity_type: str, entity_id: int) -> None:
    model = ENTITY_MODEL_MAP.get(entity_type)
    if not model:
        raise TagServiceError(f"unsupported entity_type '{entity_type}'")
    if db.get(model, entity_id) is None:
        raise TagServiceError(f"{entity_type} {entity_id} not found")


def create_tag(
    db: Session,
    *,
    name: str,
    color: Optional[str],
    description: Optional[str],
    actor: Optional[str],
) -> models.Tag:
    _ensure_tags_table(db)
    normalized = _normalize_tag_name(name)
    stmt = select(models.Tag).where(func.lower(models.Tag.name) == normalized)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        raise TagServiceError("tag name already exists")
    tag = models.Tag(name=normalized, color=color, description=description)
    now = datetime.now(timezone.utc)
    if getattr(tag, "created_at", None) is None:
        tag.created_at = now
    if getattr(tag, "updated_at", None) is None:
        tag.updated_at = now
    db.add(tag)
    db.flush()
    _log_audit(
        db,
        event_type="tag.create",
        actor=actor,
        description=f"tag '{normalized}' created",
        payload={"tag_id": tag.id},
    )
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(
    db: Session,
    tag: models.Tag,
    *,
    color: Optional[str],
    description: Optional[str],
    is_deprecated: Optional[bool],
    actor: Optional[str],
) -> models.Tag:
    changed = False
    if color is not None and color != tag.color:
        tag.color = color
        changed = True
    if description is not None and description != tag.description:
        tag.description = description
        changed = True
    if is_deprecated is not None and is_deprecated != tag.is_deprecated:
        tag.is_deprecated = is_deprecated
        changed = True
    if not changed:
        return tag
    tag.updated_at = datetime.now(timezone.utc)
    _log_audit(
        db,
        event_type="tag.update",
        actor=actor,
        description=f"tag '{tag.name}' updated",
        payload={"tag_id": tag.id},
    )
    db.commit()
    db.refresh(tag)
    return tag


def rename_tag(db: Session, tag: models.Tag, *, name: str, actor: Optional[str]) -> models.Tag:
    normalized = _normalize_tag_name(name)
    if normalized == tag.name:
        return tag
    conflict = db.execute(
        select(models.Tag).where(func.lower(models.Tag.name) == normalized, models.Tag.id != tag.id)
    ).scalar_one_or_none()
    if conflict:
        raise TagServiceError("tag name already exists")
    old = tag.name
    tag.name = normalized
    _log_audit(
        db,
        event_type="tag.rename",
        actor=actor,
        description=f"tag '{old}' renamed to '{normalized}'",
        payload={"tag_id": tag.id, "old_name": old, "new_name": normalized},
    )
    db.commit()
    db.refresh(tag)
    return tag


def merge_tags(
    db: Session,
    *,
    source: models.Tag,
    target: models.Tag,
    actor: Optional[str],
) -> models.Tag:
    if source.id == target.id:
        raise TagServiceError("cannot merge a tag into itself")
    # Move tag assignments
    db.execute(
        text(
            """
            UPDATE OR IGNORE tag_assignments
            SET tag_id = :target
            WHERE tag_id = :source
            """
        ),
        {"target": target.id, "source": source.id},
    )
    db.execute(
        text("DELETE FROM tag_assignments WHERE tag_id = :source"),
        {"source": source.id},
    )
    # Legacy entry tag compatibility
    try:
        db.execute(
            text(
                """
                UPDATE OR IGNORE entry_tags
                SET tag_id = :target
                WHERE tag_id = :source
                """
            ),
            {"target": target.id, "source": source.id},
        )
        db.execute(
            text("DELETE FROM entry_tags WHERE tag_id = :source"),
            {"source": source.id},
        )
    except Exception:
        # entry_tags table may not exist; ignore in that case
        pass

    source.is_deprecated = True
    _log_audit(
        db,
        event_type="tag.merge",
        actor=actor,
        description=f"tag '{source.name}' merged into '{target.name}'",
        payload={"source_id": source.id, "target_id": target.id},
    )
    db.commit()
    db.refresh(target)
    return target


def delete_tag(db: Session, tag: models.Tag, *, actor: Optional[str]) -> None:
    has_assignment = db.execute(
        select(models.TagAssignment.id).where(models.TagAssignment.tag_id == tag.id).limit(1)
    ).first()
    if has_assignment:
        raise TagServiceError("tag has active assignments; deprecate instead")
    db.delete(tag)
    _log_audit(
        db,
        event_type="tag.delete",
        actor=actor,
        description=f"tag '{tag.name}' deleted",
        payload={"tag_id": tag.id},
    )
    db.commit()


def assign_tag(
    db: Session,
    *,
    tag_id: Optional[int],
    tag_name: Optional[str],
    entity_type: str,
    entity_id: int,
    scope: Optional[str],
    actor: Optional[str],
    commit: bool = True,
) -> models.TagAssignment:
    if not tag_id and not tag_name:
        raise TagServiceError("tag_id or tag_name required")

    tag: Optional[models.Tag] = None
    if tag_id:
        tag = db.get(models.Tag, tag_id)
        if not tag:
            raise TagServiceError(f"tag {tag_id} not found")
    else:
        normalized = _normalize_tag_name(tag_name or "")
        tag = db.execute(
            select(models.Tag).where(func.lower(models.Tag.name) == normalized)
        ).scalar_one_or_none()
        if not tag:
            tag = models.Tag(name=normalized)
            db.add(tag)
            db.flush()
            _log_audit(
                db,
                event_type="tag.create",
                actor=actor,
                description=f"tag '{normalized}' auto-created via assignment",
                payload={"tag_id": tag.id},
            )

    entity_type_norm = (entity_type or "").strip().lower()
    if entity_type_norm not in VALID_ENTITY_TYPES:
        raise TagServiceError(f"unsupported entity_type '{entity_type}'")
    _ensure_entity_exists(db, entity_type_norm, entity_id)
    scope_norm = _normalize_scope(scope)

    existing = db.execute(
        select(models.TagAssignment).where(
            models.TagAssignment.tag_id == tag.id,
            models.TagAssignment.entity_type == entity_type_norm,
            models.TagAssignment.entity_id == entity_id,
            models.TagAssignment.scope == scope_norm,
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    assignment = models.TagAssignment(
        tag_id=tag.id,
        entity_type=entity_type_norm,
        entity_id=entity_id,
        scope=scope_norm,
    )
    db.add(assignment)
    db.flush()
    _log_audit(
        db,
        event_type="tag.assign",
        actor=actor,
        description=f"tag '{tag.name}' assigned to {entity_type_norm}:{entity_id}",
        payload={
            "tag_id": tag.id,
            "entity_type": entity_type_norm,
            "entity_id": entity_id,
            "scope": scope_norm,
        },
    )
    if commit:
        db.commit()
        db.refresh(assignment)
    return assignment


def unassign_tag(
    db: Session,
    *,
    tag_id: Optional[int],
    tag_name: Optional[str],
    entity_type: str,
    entity_id: int,
    scope: Optional[str],
    actor: Optional[str],
    commit: bool = True,
) -> None:
    if not tag_id and not tag_name:
        raise TagServiceError("tag_id or tag_name required")

    scope_norm = _normalize_scope(scope)
    entity_type_norm = (entity_type or "").strip().lower()
    if entity_type_norm not in VALID_ENTITY_TYPES:
        raise TagServiceError(f"unsupported entity_type '{entity_type}'")

    tag: Optional[models.Tag] = None
    if tag_id:
        tag = db.get(models.Tag, tag_id)
    else:
        normalized = _normalize_tag_name(tag_name or "")
        tag = db.execute(
            select(models.Tag).where(func.lower(models.Tag.name) == normalized)
        ).scalar_one_or_none()
    if not tag:
        return

    assignment = db.execute(
        select(models.TagAssignment).where(
            models.TagAssignment.tag_id == tag.id,
            models.TagAssignment.entity_type == entity_type_norm,
            models.TagAssignment.entity_id == entity_id,
            models.TagAssignment.scope == scope_norm,
        )
    ).scalar_one_or_none()
    if not assignment:
        return

    db.delete(assignment)
    _log_audit(
        db,
        event_type="tag.unassign",
        actor=actor,
        description=f"tag '{tag.name}' removed from {entity_type_norm}:{entity_id}",
        payload={
            "tag_id": tag.id,
            "entity_type": entity_type_norm,
            "entity_id": entity_id,
            "scope": scope_norm,
        },
    )
    if commit:
        db.commit()


def list_effective_tags(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
) -> List[Dict[str, Any]]:
    stmt = (
        select(
            models.EffectiveTagIndex.id,
            models.EffectiveTagIndex.entity_type,
            models.EffectiveTagIndex.entity_id,
            models.EffectiveTagIndex.tag_id,
            models.EffectiveTagIndex.scope,
            models.EffectiveTagIndex.source,
            models.EffectiveTagIndex.path_ids,
            models.EffectiveTagIndex.created_at,
            models.Tag.name.label("tag_name"),
            models.Tag.color.label("tag_color"),
        )
        .join(models.Tag, models.Tag.id == models.EffectiveTagIndex.tag_id)
        .where(
            models.EffectiveTagIndex.entity_type == entity_type,
            models.EffectiveTagIndex.entity_id == entity_id,
        )
        .order_by(models.Tag.name.asc())
    )
    rows: List[Dict[str, Any]] = []
    for row in db.execute(stmt).mappings():
        rows.append(
            {
                "id": row["id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "tag_id": row["tag_id"],
                "scope": row["scope"] or "",
                "source": row["source"],
                "path_ids": row["path_ids"],
                "created_at": row["created_at"],
                "name": row["tag_name"],
                "color": row["tag_color"],
            }
        )
    return rows


def _tag_ref(tag_id: int, name: str, color: Optional[str]) -> Dict[str, Any]:
    return {"id": tag_id, "name": name, "color": color}


def _dedupe_tag_refs(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[int] = set()
    ordered: List[Dict[str, Any]] = []
    for row in rows:
        tag_id = row["tag_id"]
        if tag_id in seen:
            continue
        seen.add(tag_id)
        ordered.append(_tag_ref(tag_id, row["name"], row["color"]))
    return ordered


def _fetch_direct_tag_refs(db: Session, entity_type: str, entity_id: int) -> List[Dict[str, Any]]:
    stmt = (
        select(models.Tag.id, models.Tag.name, models.Tag.color)
        .join(models.TagAssignment, models.TagAssignment.tag_id == models.Tag.id)
        .where(
            models.TagAssignment.entity_type == entity_type,
            models.TagAssignment.entity_id == entity_id,
        )
        .order_by(models.Tag.name.asc())
    )
    return [_tag_ref(row.id, row.name, row.color) for row in db.execute(stmt)]


def get_tag_groups(db: Session, *, entity_type: str, entity_id: int) -> Dict[str, List[Dict[str, Any]]]:
    effective_rows = list_effective_tags(db, entity_type=entity_type, entity_id=entity_id)
    direct_refs = _fetch_direct_tag_refs(db, entity_type, entity_id)
    direct_ids = {ref["id"] for ref in direct_refs}

    inherited_refs: List[Dict[str, Any]] = []
    inherited_seen: Set[int] = set()
    for row in effective_rows:
        tag_id = row["tag_id"]
        if tag_id in direct_ids or tag_id in inherited_seen:
            continue
        inherited_seen.add(tag_id)
        inherited_refs.append(_tag_ref(tag_id, row["name"], row["color"]))

    effective_refs = _dedupe_tag_refs(effective_rows)
    return {
        "direct": direct_refs,
        "inherited": inherited_refs,
        "effective": effective_refs,
    }


def get_usage(db: Session) -> List[Dict[str, Any]]:
    counts: DefaultDict[int, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))
    usage_rows = db.execute(
        select(
            models.TagAssignment.tag_id,
            models.TagAssignment.entity_type,
            func.count().label("total"),
        ).group_by(models.TagAssignment.tag_id, models.TagAssignment.entity_type)
    )
    for row in usage_rows:
        counts[row.tag_id][row.entity_type] = row.total

    tags = db.execute(select(models.Tag).order_by(models.Tag.name.asc())).scalars().all()
    result: List[Dict[str, Any]] = []
    for tag in tags:
        assignments = {
            "budget": counts[tag.id].get("budget", 0),
            "project": counts[tag.id].get("item_project", 0),
            "category": counts[tag.id].get("category", 0),
            "entry": counts[tag.id].get("entry", 0),
            "line_asset": counts[tag.id].get("line_asset", 0),
        }
        result.append(
            {
                "tag": {
                    "id": tag.id,
                    "name": tag.name,
                    "color": tag.color,
                    "is_deprecated": tag.is_deprecated,
                },
                "assignments": assignments,
            }
        )
    return result


def get_job(db: Session, job_id: int) -> Optional[models.BackgroundJob]:
    return db.get(models.BackgroundJob, job_id)


def _parse_scope_token(only_for: Optional[str]) -> Optional[Tuple[str, int]]:
    if not only_for:
        return None
    if ":" not in only_for:
        raise TagServiceError("invalid rebuild scope")
    raw_type, raw_id = only_for.split(":", 1)
    entity_alias = raw_type.strip().lower()
    alias_map = {
        "budget": "budget",
        "budgets": "budget",
        "project": "item_project",
        "item_project": "item_project",
        "category": "category",
        "categories": "category",
        "entry": "entry",
        "entries": "entry",
        "line_asset": "line_asset",
        "line_assets": "line_asset",
    }
    entity_type = alias_map.get(entity_alias)
    if not entity_type or entity_type not in VALID_ENTITY_TYPES:
        raise TagServiceError("invalid rebuild scope entity")
    try:
        entity_id = int(raw_id)
    except ValueError as exc:
        raise TagServiceError("scope id must be an integer") from exc
    if entity_id <= 0:
        raise TagServiceError("scope id must be positive")
    return entity_type, entity_id


def _build_in_clause(prefix: str, ids: Iterable[int]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    tokens: List[str] = []
    for idx, value in enumerate(ids):
        key = f"{prefix}_{idx}"
        params[key] = value
        tokens.append(f":{key}")
    return ", ".join(tokens), params


def _collect_category_subtree(db: Session, category_id: int) -> Set[int]:
    stmt = text(
        """
        WITH RECURSIVE subtree(id) AS (
            SELECT id FROM categories WHERE id = :root
            UNION ALL
            SELECT c.id
            FROM categories AS c
            JOIN subtree AS s ON c.parent_id = s.id
        )
        SELECT id FROM subtree
        """
    )
    return {row[0] for row in db.execute(stmt, {"root": category_id})}


def _collect_scope_entities(db: Session, scope: Tuple[str, int]) -> Dict[str, Set[int]]:
    entity_type, entity_id = scope
    result: Dict[str, Set[int]] = {
        "budget": set(),
        "item_project": set(),
        "category": set(),
        "line_asset": set(),
        "entry": set(),
    }

    if entity_type == "budget":
        result["budget"].add(entity_id)
        project_rows = db.execute(
            select(models.Project.id).where(models.Project.budget_id == entity_id)
        ).scalars()
        project_ids = set(project_rows)
        result["item_project"].update(project_ids)
        category_rows = db.execute(
            select(models.Category.id).where(models.Category.budget_id == entity_id)
        ).scalars()
        result["category"].update(category_rows)
        if project_ids:
            clause, params = _build_in_clause("proj", sorted(project_ids))
            if clause:
                rows = db.execute(
                    text(
                        f"SELECT line_asset_id FROM item_project_line_assets WHERE item_project_id IN ({clause})"
                    ),
                    params,
                )
                result["line_asset"].update(row[0] for row in rows)

    elif entity_type == "item_project":
        result["item_project"].add(entity_id)
        project = db.get(models.Project, entity_id)
        if project:
            result["budget"].add(project.budget_id)
            category_rows = db.execute(
                select(models.Category.id).where(models.Category.project_id == entity_id)
            ).scalars()
            result["category"].update(category_rows)
            rows = db.execute(
                select(models.ItemProjectLineAsset.line_asset_id).where(
                    models.ItemProjectLineAsset.item_project_id == entity_id
                )
            ).scalars()
            result["line_asset"].update(rows)

    elif entity_type == "category":
        category = db.get(models.Category, entity_id)
        if category:
            result["item_project"].add(category.project_id)
            result["budget"].add(category.budget_id)
        result["category"].update(_collect_category_subtree(db, entity_id))

    elif entity_type == "entry":
        result["entry"].add(entity_id)

    elif entity_type == "line_asset":
        result["line_asset"].add(entity_id)
        rows = db.execute(
            select(models.ItemProjectLineAsset.item_project_id).where(
                models.ItemProjectLineAsset.line_asset_id == entity_id
            )
        ).scalars()
        project_ids = set(rows)
        result["item_project"].update(project_ids)
        if project_ids:
            clause, params = _build_in_clause("proj", sorted(project_ids))
            if clause:
                budgets = db.execute(
                    text(
                        f"SELECT DISTINCT budget_id FROM projects WHERE id IN ({clause})"
                    ),
                    params,
                )
                result["budget"].update(row[0] for row in budgets)

    return {k: v for k, v in result.items() if v}


def _delete_scope_rows(db: Session, entities: Dict[str, Set[int]]) -> None:
    for entity_type, ids in entities.items():
        clause, params = _build_in_clause(f"del_{entity_type}", sorted(ids))
        if not clause:
            continue
        params["entity_type"] = entity_type
        db.execute(
            text(
                f"DELETE FROM effective_tag_index WHERE entity_type = :entity_type AND entity_id IN ({clause})"
            ),
            params,
        )


def _insert_direct_for_scope(db: Session, entities: Dict[str, Set[int]]) -> int:
    inserted = 0
    for entity_type, ids in entities.items():
        clause, params = _build_in_clause(f"ins_{entity_type}", sorted(ids))
        if not clause:
            continue
        params.update({"entity_type": entity_type})
        sql = text(
            f"""
            INSERT OR IGNORE INTO effective_tag_index
                (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT entity_type, entity_id, tag_id, scope, 'direct', NULL, CURRENT_TIMESTAMP
            FROM tag_assignments
            WHERE entity_type = :entity_type AND entity_id IN ({clause})
            """
        )
        result = db.execute(sql, params)
        inserted += result.rowcount or 0
    return inserted


def _insert_budget_to_projects(db: Session, project_ids: Optional[Set[int]]) -> int:
    if project_ids is not None and not project_ids:
        return 0
    params: Dict[str, Any] = {}
    where_clause = ""
    if project_ids is not None:
        clause, params = _build_in_clause("proj_budget", sorted(project_ids))
        where_clause = f"WHERE p.id IN ({clause})"
    sql = text(
        f"""
        INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
        SELECT 'item_project', p.id, ta.tag_id, ta.scope, 'inherit:budget', json_array(p.budget_id), CURRENT_TIMESTAMP
        FROM projects AS p
        JOIN tag_assignments AS ta
          ON ta.entity_type = 'budget' AND ta.entity_id = p.budget_id
        {where_clause}
        """
    )
    return db.execute(sql, params).rowcount or 0


def _insert_budget_to_categories(db: Session, category_ids: Optional[Set[int]]) -> int:
    if category_ids is not None and not category_ids:
        return 0
    params: Dict[str, Any] = {}
    where_clause = ""
    if category_ids is not None:
        clause, params = _build_in_clause("cat_budget", sorted(category_ids))
        where_clause = f"WHERE c.id IN ({clause})"
    sql = text(
        f"""
        INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
        SELECT 'category', c.id, ta.tag_id, ta.scope, 'inherit:budget', json_array(p.budget_id), CURRENT_TIMESTAMP
        FROM categories AS c
        JOIN projects AS p ON p.id = c.project_id
        JOIN tag_assignments AS ta
          ON ta.entity_type = 'budget' AND ta.entity_id = p.budget_id
        {where_clause}
        """
    )
    return db.execute(sql, params).rowcount or 0


def _insert_item_project_to_categories(db: Session, category_ids: Optional[Set[int]]) -> int:
    if category_ids is not None and not category_ids:
        return 0
    params: Dict[str, Any] = {}
    where_clause = ""
    if category_ids is not None:
        clause, params = _build_in_clause("cat_project", sorted(category_ids))
        where_clause = f"WHERE c.id IN ({clause})"
    sql = text(
        f"""
        INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
        SELECT 'category', c.id, ta.tag_id, ta.scope, 'inherit:item_project', json_array(c.project_id), CURRENT_TIMESTAMP
        FROM categories AS c
        JOIN tag_assignments AS ta
          ON ta.entity_type = 'item_project' AND ta.entity_id = c.project_id
        {where_clause}
        """
    )
    return db.execute(sql, params).rowcount or 0


def _insert_category_ancestry(db: Session, category_ids: Optional[Set[int]]) -> int:
    params: Dict[str, Any] = {}
    extra_filter = ""
    if category_ids is not None:
        if not category_ids:
            return 0
        clause, params = _build_in_clause("cat_ancestor", sorted(category_ids))
        extra_filter = f"AND a.category_id IN ({clause})"
    sql = text(
        f"""
        WITH RECURSIVE ancestors(category_id, ancestor_id) AS (
            SELECT id, parent_id
            FROM categories
            WHERE parent_id IS NOT NULL
            UNION ALL
            SELECT a.category_id, c.parent_id
            FROM ancestors AS a
            JOIN categories AS c ON c.id = a.ancestor_id
            WHERE c.parent_id IS NOT NULL
        )
        INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
        SELECT 'category', a.category_id, ta.tag_id, ta.scope, 'inherit:category', json_array(a.ancestor_id), CURRENT_TIMESTAMP
        FROM ancestors AS a
        JOIN tag_assignments AS ta
          ON ta.entity_type = 'category' AND ta.entity_id = a.ancestor_id
        WHERE a.ancestor_id IS NOT NULL
        {extra_filter}
        """
    )
    return db.execute(sql, params).rowcount or 0


def _insert_item_project_to_line_assets(db: Session, line_asset_ids: Optional[Set[int]]) -> int:
    if line_asset_ids is not None and not line_asset_ids:
        return 0
    params: Dict[str, Any] = {}
    where_clause = ""
    if line_asset_ids is not None:
        clause, params = _build_in_clause("la_project", sorted(line_asset_ids))
        where_clause = f"WHERE ipa.line_asset_id IN ({clause})"
    sql = text(
        f"""
        INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
        SELECT 'line_asset', ipa.line_asset_id, ta.tag_id, ta.scope, 'inherit:item_project', json_array(ipa.item_project_id), CURRENT_TIMESTAMP
        FROM item_project_line_assets AS ipa
        JOIN tag_assignments AS ta
          ON ta.entity_type = 'item_project' AND ta.entity_id = ipa.item_project_id
        {where_clause}
        """
    )
    return db.execute(sql, params).rowcount or 0


def _insert_budget_to_line_assets(db: Session, line_asset_ids: Optional[Set[int]]) -> int:
    if line_asset_ids is not None and not line_asset_ids:
        return 0
    params: Dict[str, Any] = {}
    where_clause = ""
    if line_asset_ids is not None:
        clause, params = _build_in_clause("la_budget", sorted(line_asset_ids))
        where_clause = f"WHERE ipa.line_asset_id IN ({clause})"
    sql = text(
        f"""
        INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
        SELECT 'line_asset', ipa.line_asset_id, ta.tag_id, ta.scope, 'inherit:budget', json_array(p.budget_id), CURRENT_TIMESTAMP
        FROM item_project_line_assets AS ipa
        JOIN projects AS p ON p.id = ipa.item_project_id
        JOIN tag_assignments AS ta
          ON ta.entity_type = 'budget' AND ta.entity_id = p.budget_id
        {where_clause}
        """
    )
    return db.execute(sql, params).rowcount or 0


def _run_rebuild(db: Session, scope: Optional[Tuple[str, int]]) -> int:
    inserted = 0
    if scope is None:
        db.execute(text("DELETE FROM effective_tag_index"))
        inserted += db.execute(
            text(
                """
                INSERT INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
                SELECT entity_type, entity_id, tag_id, scope, 'direct', NULL, CURRENT_TIMESTAMP
                FROM tag_assignments
                """
            )
        ).rowcount or 0
        inserted += _insert_budget_to_projects(db, None)
        inserted += _insert_budget_to_categories(db, None)
        inserted += _insert_item_project_to_categories(db, None)
        inserted += _insert_category_ancestry(db, None)
        inserted += _insert_item_project_to_line_assets(db, None)
        inserted += _insert_budget_to_line_assets(db, None)
        return inserted

    entities = _collect_scope_entities(db, scope)
    if not entities:
        return 0
    _delete_scope_rows(db, entities)
    inserted += _insert_direct_for_scope(db, entities)
    inserted += _insert_budget_to_projects(db, entities.get("item_project"))
    inserted += _insert_budget_to_categories(db, entities.get("category"))
    inserted += _insert_item_project_to_categories(db, entities.get("category"))
    inserted += _insert_category_ancestry(db, entities.get("category"))
    inserted += _insert_item_project_to_line_assets(db, entities.get("line_asset"))
    inserted += _insert_budget_to_line_assets(db, entities.get("line_asset"))
    return inserted


def rebuild_effective_tags(
    db: Session,
    *,
    actor: Optional[str],
    only_for: Optional[str] = None,
) -> models.BackgroundJob:
    scope = _parse_scope_token(only_for)
    job = models.BackgroundJob(kind="rebuild_effective_tags", status="running")
    job.started_at = datetime.now(timezone.utc)
    if only_for:
        job.payload = json.dumps({"scope": only_for})
    db.add(job)
    db.flush()

    _log_audit(
        db,
        event_type="job.start",
        actor=actor,
        description="effective tags rebuild started",
        payload={"job_id": job.id, "scope": only_for or "all"},
    )

    try:
        inserted = _run_rebuild(db, scope)
        job.status = "success"
        job.finished_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        _log_audit(
            db,
            event_type="job.finish",
            actor=actor,
            description="effective tags rebuild finished",
            payload={"job_id": job.id, "scope": only_for or "all", "inserted_rows": inserted},
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - surfaced in tests as failure
        job.status = "error"
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        _log_audit(
            db,
            event_type="job.error",
            actor=actor,
            description="effective tags rebuild failed",
            payload={"job_id": job.id, "scope": only_for or "all", "error": str(exc)},
        )
        db.commit()
        raise

    db.refresh(job)
    return job
