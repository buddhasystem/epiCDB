"""
serializers.py — to_dict() helpers producing plain, MCP/JSON-safe dicts.

Two flavors per domain:
  *_brief   cheap, list-safe (search results, listings — no N+1-heavy joins)
  *_detail  full detail incl. properties/logs/sources (single-item lookups)

Every function here returns only str / int / float / bool / None / list /
dict — no ORM objects, UUID objects, Decimal, or datetime instances — so
the result serializes directly to JSON for an MCP tool response without a
custom encoder.
"""
from __future__ import annotations

from ._bootstrap import _m


def _s(x) -> str | None:
    """str() an object, or None through."""
    return str(x) if x is not None else None


# ---------------------------------------------------------------------
# Catalog (Component)
# ---------------------------------------------------------------------

def component_brief(c) -> dict:
    return {
        "id": str(c.pk),
        "name": c.name,
        "model_number": c.model_number,
        "technical_system": _s(c.technical_system),
        "project": c.project,
    }


def component_detail(c) -> dict:
    m = _m()
    sources = m.ComponentSource.objects.filter(component=c).select_related("source")
    properties = m.PropertyValue.objects.filter(component=c).select_related("property_type")
    logs = (
        m.LogEntry.objects.filter(component=c)
        .select_related("logged_by")
        .order_by("-timestamp")[:50]
    )
    return {
        **component_brief(c),
        "description": c.description,
        "owner_group": _s(c.owner_group),
        "owner_user": c.owner_user.username if c.owner_user else None,
        "instance_count": m.ComponentInstance.objects.filter(component=c).count(),
        "sources": [
            {
                "vendor": cs.source.name,
                "part_number": cs.part_number,
                "cost": float(cs.cost) if cs.cost is not None else None,
                "role": cs.role,
            }
            for cs in sources
        ],
        "properties": [
            {"type": p.property_type.name, "tag": p.tag, "value": p.value, "units": p.units}
            for p in properties
        ],
        "recent_logs": [
            {
                "timestamp": str(l.timestamp),
                "topic": l.topic,
                "entry": l.entry,
                "by": str(l.logged_by) if l.logged_by else None,
            }
            for l in logs
        ],
    }


# ---------------------------------------------------------------------
# Inventory (ComponentInstance)
# ---------------------------------------------------------------------

def instance_brief(i) -> dict:
    return {
        "id": str(i.pk),
        "tag": i.tag,
        "serial_number": i.serial_number,
        "component": i.component.name if i.component else None,
        "location": _s(i.location),
        "institution": _s(i.location.institution) if i.location else None,
    }


def instance_detail(i) -> dict:
    m = _m()
    properties = m.PropertyValue.objects.filter(component_instance=i).select_related("property_type")
    logs = (
        m.LogEntry.objects.filter(component_instance=i)
        .select_related("logged_by")
        .order_by("-timestamp")[:50]
    )
    return {
        **instance_brief(i),
        "description": i.description,
        "model_number": i.component.model_number if i.component else None,
        "technical_system": _s(i.technical_system),
        "owner_group": _s(i.owner_group),
        "owner_user": i.owner_user.username if i.owner_user else None,
        "properties": [
            {"type": p.property_type.name, "tag": p.tag, "value": p.value, "units": p.units}
            for p in properties
        ],
        "logs": [
            {
                "timestamp": str(l.timestamp),
                "topic": l.topic,
                "entry": l.entry,
                "by": str(l.logged_by) if l.logged_by else None,
            }
            for l in logs
        ],
    }


# ---------------------------------------------------------------------
# Designs
# ---------------------------------------------------------------------

def design_brief(d) -> dict:
    return {"id": str(d.pk), "name": d.name, "project": d.project}


def design_detail(d, bom_fn) -> dict:
    m = _m()
    properties = m.PropertyValue.objects.filter(design=d).select_related("property_type")
    return {
        **design_brief(d),
        "description": d.description,
        "owner_group": _s(d.owner_group),
        "owner_user": d.owner_user.username if d.owner_user else None,
        "element_count": d.elements.count(),
        "properties": [
            {"type": p.property_type.name, "tag": p.tag, "value": p.value}
            for p in properties
        ],
        "bom": bom_fn(d.name),
    }


# ---------------------------------------------------------------------
# Locations / Institutions (no ownership fields — read-only reference data)
# ---------------------------------------------------------------------

def institution_brief(inst) -> dict:
    return {
        "id": inst.pk,
        "name": inst.name,
        "abbreviation": inst.abbreviation,
        "city": inst.city,
        "country": inst.country,
        "url": inst.url,
    }
