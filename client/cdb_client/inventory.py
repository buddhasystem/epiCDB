"""
InventoryClient — query Component Inventory (physical instances).
"""
from ._bootstrap import _m


class InventoryClient:
    """Query Component Inventory (physical instances)."""

    def _base_qs(self):
        return _m().ComponentInstance.objects.select_related(
            "component", "technical_system",
            "location", "location__institution",
            "owner_group", "owner_user",
        )

    def all_instances(self):
        return self._base_qs()

    def get(self, pk: str):
        """Look up a single instance by its UUID primary key."""
        return self._base_qs().get(pk=pk)

    def instances_of(self, component_name: str):
        """All physical instances of a component type."""
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
            Q(tag__icontains=query) |
            Q(serial_number__icontains=query) | Q(component__name__icontains=query)
        ).select_related("component", "technical_system", "location")

    def installed_in_design(self, design_name: str):
        """Instances occupying slots in the named design."""
        return _m().ComponentInstance.objects.filter(
            installed_at__design__name=design_name
        ).select_related("component", "technical_system", "location")

    def logs_for(self, pk: str):
        return _m().LogEntry.objects.filter(
            component_instance__pk=pk
        ).select_related("logged_by")

    def properties_for(self, pk: str):
        return _m().PropertyValue.objects.filter(
            component_instance__pk=pk
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

    def detail(self, pk: str) -> dict:
        """Plain-dict detail view of a single instance."""
        inst = self.get(pk)
        return {
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
                for p in self.properties_for(pk)
            ],
            "logs": [
                {"timestamp": str(lg.timestamp), "topic": lg.topic,
                 "entry": lg.entry, "by": str(lg.logged_by)}
                for lg in self.logs_for(pk)
            ],
        }
