"""
CatalogClient — query the Component Catalog.
"""
from ._bootstrap import _m


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
