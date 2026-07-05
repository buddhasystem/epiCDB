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
            "id":               str(inst.pk),
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

    def create(self, component, tag="", serial_number="", description="",
               location_name=None, owner_group_name=None,
               owner_username=None) -> dict:
        """Create and persist a new ComponentInstance.

        Parameters
        ----------
        component       : Component model instance (already fetched)
        tag             : human-readable label
        serial_number   : manufacturer serial number
        description     : free-text notes
        location_name   : exact Location.name string (optional)
        owner_group_name: exact Group.name string (optional)
        owner_username  : exact User.username string (optional)
        Returns the detail dict of the newly saved instance.
        """
        import uuid as _uuid
        m = _m()

        location = None
        if location_name:
            try:
                location = m.Location.objects.get(name=location_name)
            except m.Location.DoesNotExist:
                raise ValueError(f"Location not found: {location_name!r}")

        owner_group = None
        if owner_group_name:
            try:
                owner_group = m.Group.objects.get(name=owner_group_name)
            except m.Group.DoesNotExist:
                raise ValueError(f"Group not found: {owner_group_name!r}")

        owner_user = None
        if owner_username:
            from django.contrib.auth.models import User
            try:
                owner_user = User.objects.get(username=owner_username)
            except User.DoesNotExist:
                raise ValueError(f"User not found: {owner_username!r}")

        new_pk = str(_uuid.uuid4())

        inst = m.ComponentInstance(
            id=new_pk,
            component=component,
            tag=tag,
            serial_number=serial_number,
            description=description,
            location=location,
            owner_group=owner_group,
            owner_user=owner_user,
        )
        inst.save()
        return self.detail(new_pk)

