"""
DesignClient — query the Design Library.
"""
from ._bootstrap import _m


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
        """
        Recursive Bill of Materials as a nested list of dicts.
        Sub-designs are expanded under "children".
        """
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
                entry["ref"]          = el.component.name         if el.component         else None
                entry["model_number"] = el.component.model_number if el.component         else None
                entry["installed_id"] = el.installed_instance.pk    if el.installed_instance else None
                entry["children"]     = []
            rows.append(entry)
        return rows

    def flat_component_list(self, design_name: str) -> list:
        """Flatten BOM to leaf-component rows only (no sub-design rows)."""
        def _flat(rows):
            out = []
            for r in rows:
                if r["type"] == "COMPONENT":
                    out.append(r)
                out.extend(_flat(r.get("children", [])))
            return out
        return _flat(self.bom(design_name))

    def designs_using_component(self, component_name: str):
        """All designs that directly contain a given component."""
        return _m().Design.objects.filter(
            elements__component__name=component_name
        ).distinct()

    def summary(self, design_name: str) -> dict:
        """Plain-dict summary of a design, including BOM."""
        d = self.get(name=design_name)
        return {
            "id":            d.pk,
            "name":          d.name,
            "description":   d.description,
            "project":       d.project,
            "owner_group":   str(d.owner_group)        if d.owner_group else None,
            "owner_user":    d.owner_user.username      if d.owner_user else None,
            "element_count": d.elements.count(),
            "properties": [
                {"type": p.property_type.name, "tag": p.tag, "value": p.value}
                for p in self.properties_for(design_name)
            ],
            "bom": self.bom(design_name),
        }
