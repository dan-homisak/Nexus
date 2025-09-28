"""Tag management service helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Dict, Any, Iterable

from sqlalchemy import func, select, text
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


def _log_audit(
    db: Session,
    *,
    event_type: str,
    actor: Optional[str],
    description: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
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
    normalized = _normalize_tag_name(name)
    stmt = select(models.Tag).where(func.lower(models.Tag.name) == normalized)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        raise TagServiceError("tag name already exists")
    tag = models.Tag(name=normalized, color=color, description=description)
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
) -> Iterable[Dict[str, Any]]:
    stmt = text(
        """
        SELECT
            eti.id,
            eti.entity_type,
            eti.entity_id,
            eti.tag_id,
            eti.scope,
            eti.source,
            eti.path_ids,
            eti.created_at,
            t.name AS tag_name,
            t.color AS tag_color
        FROM effective_tag_index AS eti
        JOIN tags AS t ON t.id = eti.tag_id
        WHERE eti.entity_type = :entity_type AND eti.entity_id = :entity_id
        ORDER BY tag_name
        """
    )
    result = db.execute(stmt, {"entity_type": entity_type, "entity_id": entity_id})
    for row in result.mappings():
        data = dict(row)
        data["scope"] = data.get("scope") or ""
        yield data


def get_job(db: Session, job_id: int) -> Optional[models.BackgroundJob]:
    return db.get(models.BackgroundJob, job_id)


def _run_rebuild(db: Session) -> None:
    db.execute(text("DELETE FROM effective_tag_index"))

    # Direct assignments
    db.execute(
        text(
            """
            INSERT INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT entity_type, entity_id, tag_id, scope, 'direct', NULL, CURRENT_TIMESTAMP
            FROM tag_assignments
            """
        )
    )

    # Budget -> Item/Project
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT 'item_project', p.id, ta.tag_id, ta.scope, 'inherit:budget', json_array(p.budget_id), CURRENT_TIMESTAMP
            FROM projects AS p
            JOIN tag_assignments AS ta
              ON ta.entity_type = 'budget' AND ta.entity_id = p.budget_id
            """
        )
    )

    # Budget -> Category
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT 'category', c.id, ta.tag_id, ta.scope, 'inherit:budget', json_array(p.budget_id), CURRENT_TIMESTAMP
            FROM categories AS c
            JOIN projects AS p ON p.id = c.project_id
            JOIN tag_assignments AS ta
              ON ta.entity_type = 'budget' AND ta.entity_id = p.budget_id
            """
        )
    )

    # Item/Project -> Category
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT 'category', c.id, ta.tag_id, ta.scope, 'inherit:item_project', json_array(c.project_id), CURRENT_TIMESTAMP
            FROM categories AS c
            JOIN tag_assignments AS ta
              ON ta.entity_type = 'item_project' AND ta.entity_id = c.project_id
            """
        )
    )

    # Category ancestors -> Category
    db.execute(
        text(
            """
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
            """
        )
    )

    # Item/Project -> Line Asset
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT 'line_asset', ipa.line_asset_id, ta.tag_id, ta.scope, 'inherit:item_project', json_array(ipa.item_project_id), CURRENT_TIMESTAMP
            FROM item_project_line_assets AS ipa
            JOIN tag_assignments AS ta
              ON ta.entity_type = 'item_project' AND ta.entity_id = ipa.item_project_id
            """
        )
    )

    # Budget -> Line Asset via project
    db.execute(
        text(
            """
            INSERT OR IGNORE INTO effective_tag_index (entity_type, entity_id, tag_id, scope, source, path_ids, created_at)
            SELECT 'line_asset', ipa.line_asset_id, ta.tag_id, ta.scope, 'inherit:budget', json_array(p.budget_id), CURRENT_TIMESTAMP
            FROM item_project_line_assets AS ipa
            JOIN projects AS p ON p.id = ipa.item_project_id
            JOIN tag_assignments AS ta
              ON ta.entity_type = 'budget' AND ta.entity_id = p.budget_id
            """
        )
    )


def rebuild_effective_tags(db: Session, *, actor: Optional[str]) -> models.BackgroundJob:
    job = models.BackgroundJob(kind="rebuild_effective_tags", status="running")
    job.started_at = datetime.utcnow()
    db.add(job)
    db.flush()

    _log_audit(
        db,
        event_type="job.start",
        actor=actor,
        description="effective tags rebuild started",
        payload={"job_id": job.id},
    )

    try:
        _run_rebuild(db)
        job.status = "success"
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        _log_audit(
            db,
            event_type="job.finish",
            actor=actor,
            description="effective tags rebuild finished",
            payload={"job_id": job.id},
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - surfaced in tests as failure
        job.status = "error"
        job.error = str(exc)
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        _log_audit(
            db,
            event_type="job.error",
            actor=actor,
            description="effective tags rebuild failed",
            payload={"job_id": job.id, "error": str(exc)},
        )
        db.commit()
        raise

    db.refresh(job)
    return job
