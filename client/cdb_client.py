"""
cdb_client.py  —  Programmatic query client for the Component Database (CDB).

Five domain clients:
    LocationClient  — institutions and location hierarchy
    SystemClient    — technical systems
    CatalogClient   — component catalog
    InventoryClient — physical component instances
    DesignClient    — design / BOM library

One combined entry point:
    CDBClient       — aggregates all five

All methods return Django QuerySets (lazy, chainable) unless the docstring
says "plain dict" or "list of dicts".

Primary keys are UUID strings (CharField, length 36) on all models.
Groups are Django's built-in auth.Group (integer PK).

Bootstrap (outside Django shell):
    import sys, os
    sys.path.insert(0, "/path/to/cdb_project")
    os.environ["DJANGO_SETTINGS_MODULE"] = "cdb_project.settings"
    import django; django.setup()
    from cdb_client import CDBClient
"""

import os, sys, django, django.conf


def _bootstrap(settings_module="cdb_project.settings", project_root=None):
    if project_root:
        sys.path.insert(0, project_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    if not django.conf.settings.configured:
        django.setup()


def _m():
    from cdb import models
    return models


# =============================================================================
# LocationClient
# =============================================================================

class LocationClient:
    """Query Institutions and Locations."""

    def all_institutions(self):
        return _m().Institution.objects.all()

    def get_institution(self, abbreviation=None, name=None):
        m = _m()
        if abbreviation:
            return m.Institution.objects.get(abbreviation=abbreviation)
        return m.Institution.objects.get(name=name)

    def institutions_by_country(self, country: str):
        return _m().Institution.objects.filter(country__iexact=country)

    def all_locations(self):
        return _m().Location.objects.select_related("institution", "parent")

    def locations_at_institution(self, abbreviation: str):
        return _m().Location.objects.filter(
            institution__abbreviation=abbreviation
        ).select_related("parent")

    def buildings(self, institution_abbr=None):
        qs = _m().Location.objects.filter(location_type="building")
        if institution_abbr:
            qs = qs.filter(institution__abbreviation=institution_abbr)
        return qs.select_related("institution")

    def rooms_in_building(self, building_name: str, institution_abbr=None):
        qs = _m().Location.objects.filter(
            location_type="room", parent__name=building_name)
        if institution_abbr:
            qs = qs.filter(institution__abbreviation=institution_abbr)
        return qs

    def location_tree(self, institution_abbr: str) -> list:
        """Nested list-of-dicts for the full location hierarchy at an institution."""
        locs = list(
            _m().Location.objects.filter(
                institution__abbreviation=institution_abbr
            ).select_related("parent").order_by("location_type", "name")
        )
        id_map = {
            loc.pk: {"id": loc.pk, "name": loc.name,
                     "type": loc.location_type, "children": []}
            for loc in locs
        }
        roots = []
        for loc in locs:
            node = id_map[loc.pk]
            if loc.parent_id and loc.parent_id in id_map:
                id_map[loc.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return roots

    def users_at_institution(self, abbreviation: str):
        """Return UserProfile queryset for all users attached to an institution."""
        return _m().UserProfile.objects.filter(
            institution__abbreviation=abbreviation
        ).select_related("user", "institution")


# =============================================================================
# SystemClient
# =============================================================================

class SystemClient:
    """Query TechnicalSystem entries and their associated components/instances."""

    def all(self):
        return _m().TechnicalSystem.objects.all()

    def get(self, name=None, pk=None):
        m = _m()
        if pk:
            return m.TechnicalSystem.objects.get(pk=pk)
        return m.TechnicalSystem.objects.get(name__iexact=name)

    def components(self, system_name: str):
        """All components assigned to this technical system."""
        return _m().Component.objects.filter(
            technical_system__name__iexact=system_name
        ).select_related("owner_group")

    def instances(self, system_name: str):
        """All component instances directly tagged with this technical system."""
        return _m().ComponentInstance.objects.filter(
            technical_system__name__iexact=system_name
        ).select_related(
            "component", "location", "location__institution",
            "owner_group", "owner_user",
        )

    def summary(self, system_name: str) -> dict:
        """Plain-dict summary of a technical system."""
        from django.db.models import Count
        sys = self.get(name=system_name)
        return {
            "id":             sys.pk,
            "name":           sys.name,
            "description":    sys.description,
            "component_count": _m().Component.objects.filter(technical_system=sys).count(),
            "instance_count":  _m().ComponentInstance.objects.filter(technical_system=sys).count(),
        }

    def instance_counts(self) -> list:
        """List of dicts with instance counts per technical system."""
        from django.db.models import Count
        rows = (
            _m().TechnicalSystem.objects
            .annotate(
                component_count=Count("components", distinct=True),
                instance_count=Count("component_instances", distinct=True),
            )
            .order_by("name")
        )
        return [
            {"name": r.name, "components": r.component_count,
             "instances": r.instance_count}
            for r in rows
        ]


# =============================================================================
# CatalogClient
# =============================================================================

class CatalogClient:
    """Query the Component Catalog."""

    def all_components(self):
        return _m().Component.objects.select_related(
            "technical_system", "owner_group", "owner_user"
        )

    def search(self, query: str):
        """Full-text search across name, alternate name, model number, description."""
        from django.db.models import Q
        return _m().Component.objects.filter(
            Q(name__icontains=query) | Q(alternate_name__icontains=query) |
            Q(model_number__icontains=query) | Q(description__icontains=query)
        ).select_related("technical_system", "owner_group")

    def by_technical_system(self, system_name: str):
        return _m().Component.objects.filter(
            technical_system__name__iexact=system_name
        ).select_related("owner_group", "owner_user")

    def by_project(self, project: str):
        return _m().Component.objects.filter(
            project__iexact=project
        ).select_related("technical_system", "owner_group")

    def get(self, name=None, model_number=None, pk=None):
        m = _m()
        if pk:           return m.Component.objects.get(pk=pk)
        if model_number: return m.Component.objects.get(model_number=model_number)
        return m.Component.objects.get(name=name)

    def sources_for(self, component_name: str):
        return _m().ComponentSource.objects.filter(
            component__name=component_name
        ).select_related("source")

    def properties_for(self, component_name: str):
        return _m().PropertyValue.objects.filter(
            component__name=component_name
        ).select_related("property_type")

    def logs_for(self, component_name: str):
        return _m().LogEntry.objects.filter(
            component__name=component_name
        ).select_related("logged_by")

    def instance_count(self, component_name: str) -> int:
        return _m().ComponentInstance.objects.filter(
            component__name=component_name
        ).count()

    def summary(self, component_name: str) -> dict:
        """Plain-dict summary of a component."""
        c = self.get(name=component_name)
        return {
            "id":               c.pk,
            "name":             c.name,
            "model_number":     c.model_number,
            "description":      c.description,
            "technical_system": str(c.technical_system) if c.technical_system else None,
            "project":          c.project,
            "owner_group":      str(c.owner_group) if c.owner_group else None,
            "owner_user":       c.owner_user.username if c.owner_user else None,
            "instance_count":   self.instance_count(component_name),
            "sources": [
                {"vendor":      cs.source.name,
                 "part_number": cs.part_number,
                 "cost":        float(cs.cost) if cs.cost else None,
                 "role":        cs.role}
                for cs in self.sources_for(component_name)
            ],
            "properties": [
                {"type":  pv.property_type.name, "tag": pv.tag,
                 "value": pv.value, "units": pv.units}
                for pv in self.properties_for(component_name)
            ],
        }


# =============================================================================
# InventoryClient
# =============================================================================

class InventoryClient:
    """Query Component Inventory (physical instances)."""

    def all_instances(self):
        return _m().ComponentInstance.objects.select_related(
            "component", "technical_system",
            "location", "location__institution",
            "owner_group", "owner_user",
        )

    def get_by_qr(self, qr_id: str):
        return _m().ComponentInstance.objects.select_related(
            "component", "technical_system",
            "location", "location__institution",
            "owner_group", "owner_user",
        ).get(qr_id=qr_id)

    def instances_of(self, component_name: str):
        return _m().ComponentInstance.objects.filter(
            component__name=component_name
        ).select_related(
            "technical_system", "location",
            "location__institution", "owner_group", "owner_user",
        )

    def by_technical_system(self, system_name: str):
        """All instances directly tagged with the given technical system."""
        return _m().ComponentInstance.objects.filter(
            technical_system__name__iexact=system_name
        ).select_related(
            "component", "location",
            "location__institution", "owner_group", "owner_user",
        )

    def at_institution(self, abbreviation: str):
        return _m().ComponentInstance.objects.filter(
            location__institution__abbreviation=abbreviation
        ).select_related(
            "component", "technical_system",
            "location", "owner_group", "owner_user",
        )

    def at_location(self, location_name: str, institution_abbr=None):
        qs = _m().ComponentInstance.objects.filter(location__name=location_name)
        if institution_abbr:
            qs = qs.filter(location__institution__abbreviation=institution_abbr)
        return qs.select_related(
            "component", "technical_system", "location__institution"
        )

    def by_group(self, group_name: str):
        return _m().ComponentInstance.objects.filter(
            owner_group__name=group_name
        ).select_related("component", "technical_system", "location")

    def by_owner(self, username: str):
        """All instances where owner_user matches the given username."""
        return _m().ComponentInstance.objects.filter(
            owner_user__username=username
        ).select_related(
            "component", "technical_system",
            "location", "location__institution", "owner_group",
        )

    def search(self, query: str):
        from django.db.models import Q
        return _m().ComponentInstance.objects.filter(
            Q(qr_id__icontains=query) | Q(tag__icontains=query) |
            Q(serial_number__icontains=query) | Q(component__name__icontains=query)
        ).select_related("component", "technical_system", "location")

    def installed_in_design(self, design_name: str):
        return _m().ComponentInstance.objects.filter(
            installed_at__design__name=design_name
        ).select_related("component", "technical_system", "location")

    def logs_for(self, qr_id: str):
        return _m().LogEntry.objects.filter(
            component_instance__qr_id=qr_id
        ).select_related("logged_by")

    def properties_for(self, qr_id: str):
        return _m().PropertyValue.objects.filter(
            component_instance__qr_id=qr_id
        ).select_related("property_type")

    def institution_summary(self) -> list:
        """Instance counts grouped by institution."""
        from django.db.models import Count
        rows = (
            _m().ComponentInstance.objects
            .values("location__institution__abbreviation")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )
        return [
            {"institution": r["location__institution__abbreviation"] or "Unknown",
             "count":       r["count"]}
            for r in rows
        ]

    def system_summary(self) -> list:
        """Instance counts grouped by technical system."""
        from django.db.models import Count
        rows = (
            _m().ComponentInstance.objects
            .values("technical_system__name")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )
        return [
            {"technical_system": r["technical_system__name"] or "Unassigned",
             "count":            r["count"]}
            for r in rows
        ]

    def detail(self, qr_id: str) -> dict:
        """Plain-dict detail view of a single instance."""
        inst = self.get_by_qr(qr_id)
        return {
            "qr_id":            inst.qr_id,
            "tag":              inst.tag,
            "serial_number":    inst.serial_number,
            "description":      inst.description,
            "component":        inst.component.name,
            "model_number":     inst.component.model_number,
            "technical_system": str(inst.technical_system) if inst.technical_system else None,
            "location":         str(inst.location)             if inst.location else None,
            "institution":      str(inst.location.institution) if inst.location else None,
            "owner_group":      str(inst.owner_group)          if inst.owner_group else None,
            "owner_user":       inst.owner_user.username       if inst.owner_user else None,
            "properties": [
                {"type": p.property_type.name, "tag": p.tag,
                 "value": p.value, "units": p.units}
                for p in self.properties_for(qr_id)
            ],
            "logs": [
                {"timestamp": str(lg.timestamp), "topic": lg.topic,
                 "entry": lg.entry, "by": str(lg.logged_by)}
                for lg in self.logs_for(qr_id)
            ],
        }


# =============================================================================
# DesignClient
# =============================================================================

class DesignClient:
    """Query the Design Library."""

    def all_designs(self):
        return _m().Design.objects.select_related("owner_group", "owner_user")

    def get(self, name=None, pk=None):
        m = _m()
        if pk:   return m.Design.objects.get(pk=pk)
        return m.Design.objects.get(name=name)

    def by_project(self, project: str):
        return _m().Design.objects.filter(project__iexact=project)

    def search(self, query: str):
        from django.db.models import Q
        return _m().Design.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    def elements_of(self, design_name: str):
        return _m().DesignElement.objects.filter(
            design__name=design_name
        ).select_related("component", "child_design", "installed_instance")

    def properties_for(self, design_name: str):
        return _m().PropertyValue.objects.filter(
            design__name=design_name
        ).select_related("property_type")

    def logs_for(self, design_name: str):
        return _m().LogEntry.objects.filter(
            design__name=design_name
        ).select_related("logged_by")

    def bom(self, design_name: str, _depth=0, _max=10) -> list:
        """Recursive Bill of Materials as a nested list of dicts."""
        if _depth > _max:
            return [{"error": "max depth exceeded"}]
        rows = []
        for el in self.elements_of(design_name):
            entry = {
                "element":     el.element_name,
                "type":        el.element_type(),
                "qty":         el.quantity,
                "description": el.description,
            }
            if el.child_design:
                entry["ref"]      = el.child_design.name
                entry["children"] = self.bom(el.child_design.name, _depth + 1, _max)
            else:
                entry["ref"]          = el.component.name        if el.component         else None
                entry["model_number"] = el.component.model_number if el.component         else None
                entry["installed_qr"] = el.installed_instance.qr_id if el.installed_instance else None
                entry["children"]     = []
            rows.append(entry)
        return rows

    def flat_component_list(self, design_name: str) -> list:
        """Flattened list of COMPONENT-type BOM rows (no sub-designs)."""
        def _flat(rows):
            out = []
            for r in rows:
                if r["type"] == "COMPONENT":
                    out.append(r)
                out.extend(_flat(r.get("children", [])))
            return out
        return _flat(self.bom(design_name))

    def designs_using_component(self, component_name: str):
        return _m().Design.objects.filter(
            elements__component__name=component_name
        ).distinct()

    def summary(self, design_name: str) -> dict:
        """Plain-dict summary of a design."""
        d = self.get(name=design_name)
        return {
            "id":            d.pk,
            "name":          d.name,
            "description":   d.description,
            "project":       d.project,
            "owner_group":   str(d.owner_group) if d.owner_group else None,
            "owner_user":    d.owner_user.username if d.owner_user else None,
            "element_count": d.elements.count(),
            "properties": [
                {"type": p.property_type.name, "tag": p.tag, "value": p.value}
                for p in self.properties_for(design_name)
            ],
            "bom": self.bom(design_name),
        }


# =============================================================================
# CDBClient — unified entry point
# =============================================================================

class CDBClient:
    """Single entry point for all CDB domains."""

    def __init__(self):
        self.locations = LocationClient()
        self.systems   = SystemClient()
        self.catalog   = CatalogClient()
        self.inventory = InventoryClient()
        self.designs   = DesignClient()

    def search_all(self, query: str) -> dict:
        """Cross-domain search returning UUID id, display name, and type."""
        return {
            "components": list(
                self.catalog.search(query).values("id", "name", "model_number")
            ),
            "instances": list(
                self.inventory.search(query).values("id", "qr_id", "tag")
            ),
            "designs": list(
                self.designs.search(query).values("id", "name")
            ),
        }

    def where_is(self, qr_id: str) -> dict:
        """Return location dict for a single instance looked up by QR code."""
        inst = self.inventory.get_by_qr(qr_id)
        loc  = inst.location
        return {
            "qr_id":            qr_id,
            "component":        inst.component.name,
            "technical_system": str(inst.technical_system) if inst.technical_system else None,
            "location":         str(loc)              if loc else None,
            "institution":      str(loc.institution)  if loc else None,
            "city":             loc.institution.city    if loc else None,
            "country":          loc.institution.country if loc else None,
        }


# =============================================================================
# Demo when run as a script
# =============================================================================

if __name__ == "__main__":
    import json

    _bootstrap(
        settings_module="cdb_project.settings",
        project_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )

    client = CDBClient()

    print("\n-- Institutions --------------------------------------------------")
    for i in client.locations.all_institutions():
        print(f"  {i.abbreviation:6}  {i.city}, {i.country}")

    print("\n-- Location tree at BNL ------------------------------------------")
    print(json.dumps(client.locations.location_tree("BNL"), indent=2))

    print("\n-- Technical systems: instance counts ----------------------------")
    for row in client.systems.instance_counts():
        print(f"  {row['name']:30}  components={row['components']:3}  instances={row['instances']}")

    print("\n-- Catalog search: 'sensor' --------------------------------------")
    for c in client.catalog.search("sensor"):
        print(f"  [{c.pk}] {c.name}  ({c.model_number})")

    print("\n-- Component summary ---------------------------------------------")
    print(json.dumps(
        client.catalog.summary("ePIC SVT Silicon Strip Sensor"),
        indent=2, default=str
    ))

    print("\n-- Inventory by institution --------------------------------------")
    for row in client.inventory.institution_summary():
        print(f"  {row['institution']:6}  {row['count']} instance(s)")

    print("\n-- Inventory by technical system ---------------------------------")
    for row in client.inventory.system_summary():
        print(f"  {row['technical_system']:30}  {row['count']} instance(s)")

    print("\n-- Where is QR 000-001-003? --------------------------------------")
    print(json.dumps(client.where_is("000-001-003"), indent=2))

    print("\n-- BOM: ePIC Tracking System -------------------------------------")
    print(json.dumps(
        client.designs.bom("ePIC Tracking System"),
        indent=2, default=str
    ))

    print("\n-- Flat component list: SVT Layer 1 Module -----------------------")
    for row in client.designs.flat_component_list("ePIC SVT Layer 1 Module"):
        print(f"  {row['element']:25}  {row['ref']}")

    print("\n-- Designs using SVT strip sensor --------------------------------")
    for d in client.designs.designs_using_component("ePIC SVT Silicon Strip Sensor"):
        print(f"  {d.name}")

    print("\ndone.")
