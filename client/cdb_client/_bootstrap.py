"""
Shared Django bootstrap and model accessor used by all domain modules.
Unchanged from the original client/cdb_client/_bootstrap.py.
"""
import os, sys, django, django.conf


def _bootstrap(settings_module="cdb_project.settings", project_root=None):
    """Configure Django if it has not already been set up."""
    if project_root:
        sys.path.insert(0, project_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    if not django.conf.settings.configured:
        django.setup()


def _m():
    """Lazy import of cdb.models to avoid early Django import errors."""
    from cdb import models
    return models
