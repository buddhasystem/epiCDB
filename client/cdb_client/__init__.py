"""
cdb_client — Programmatic query client for the Component Database (CDB).

Usage inside the Django shell or any configured Django environment:

    from cdb_client import CDBClient
    client = CDBClient()
    client.where_is("000-001-003")

Usage outside Django (standalone script):

    from cdb_client._bootstrap import _bootstrap
    _bootstrap(project_root="/path/to/epiCDB")
    from cdb_client import CDBClient
    client = CDBClient()
"""
from .client    import CDBClient
from .locations import LocationClient
from .systems   import SystemClient
from .catalog   import CatalogClient
from .inventory import InventoryClient
from .designs   import DesignClient

__all__ = [
    "CDBClient",
    "LocationClient",
    "SystemClient",
    "CatalogClient",
    "InventoryClient",
    "DesignClient",
]
