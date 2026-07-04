"""
CDBClient — unified entry point aggregating all domain clients.
"""
from .locations import LocationClient
from .systems   import SystemClient
from .catalog   import CatalogClient
from .inventory import InventoryClient
from .designs   import DesignClient


class CDBClient:
    """Single entry point for all CDB domains."""

    def __init__(self):
        self.locations = LocationClient()
        self.systems   = SystemClient()
        self.catalog   = CatalogClient()
        self.inventory = InventoryClient()
        self.designs   = DesignClient()

    def search_all(self, query: str) -> dict:
        """Cross-domain search: components, instances, and designs."""
        return {
            "components": list(
                self.catalog.search(query).values("id", "name", "model_number")
            ),
            "instances": list(
                self.inventory.search(query).values("id", "tag", "serial_number")
            ),
            "designs": list(
                self.designs.search(query).values("id", "name")
            ),
        }

    def where_is(self, pk: str) -> dict:
        """Return location dict for a single instance looked up by UUID primary key."""
        inst = self.inventory.get(pk)
        loc  = inst.location
        return {
            "id":               pk,
            "component":        inst.component.name,
            "technical_system": str(inst.technical_system) if inst.technical_system else None,
            "location":         str(loc)              if loc else None,
            "institution":      str(loc.institution)  if loc else None,
            "city":             loc.institution.city    if loc else None,
            "country":          loc.institution.country if loc else None,
        }
