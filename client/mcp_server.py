"""
mcp_server.py — MCP server for the Component Database (CDB), user-facing.

Authentication model
---------------------
HTTP Basic Auth, validated against Django's own auth.User table via
django.contrib.auth.authenticate(). There is no separate credential
store: whatever accounts already exist in the CDB database (created via
/admin/, `createsuperuser`, or your own signup flow) are exactly the
accounts that can use this MCP server. Passwords are never handled by
this file beyond passing them straight into Django's authenticate() —
they are checked against Django's existing salted-hash storage and are
never logged, stored, or echoed back.

Every authenticated request is bound to a Django User for its duration,
via a contextvar (see AuthContext below). Every tool builds a
CDBClient(user=...) scoped to that user, so writes are permission-checked
and the ownership hooks in cdb_client/access.py apply uniformly.

Transport
---------
This server only supports Streamable HTTP (not stdio). Basic Auth only
makes sense when there's a request per call to attach credentials to;
stdio is a single trusted local process with no per-call identity, so
it is intentionally not wired up here. If you need a local/dev mode,
use the existing CLI (`client/cdb.py`) directly instead, via
CDBClient(user=None).

NOTE ON LIBRARY VERSIONS
-------------------------
This uses `mcp.server.fastmcp.FastMCP` from the official Python MCP SDK,
and wraps its ASGI app with a Starlette middleware for Basic Auth. The
exact method name FastMCP exposes for the Streamable HTTP ASGI app
(`streamable_http_app()` below) has changed across SDK versions — check
`python -c "from mcp.server.fastmcp import FastMCP; print(dir(FastMCP))"`
against your installed version and adjust the one call site marked below
if it differs.

Setup
-----
    pip install "mcp[cli]" django starlette uvicorn asgiref

    # from the epiCDB project root (next to manage.py):
    DJANGO_SETTINGS_MODULE=cdb_project.settings \
    CDB_PROJECT_ROOT=/path/to/epiCDB \
    python client/mcp_server.py
"""
from __future__ import annotations

import base64
import os
import sys
import time
import threading
from contextvars import ContextVar
from typing import Optional

# ---------------------------------------------------------------------
# 1. Django bootstrap — must happen before any Django or cdb_client import
# ---------------------------------------------------------------------
PROJECT_ROOT = os.environ.get("CDB_PROJECT_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cdb_project.settings")

import django  # noqa: E402
import django.conf  # noqa: E402

if not django.conf.settings.configured:
    django.setup()

from django.contrib.auth import authenticate  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402

from cdb_client import CDBClient  # noqa: E402
from cdb_client.serializers import instance_brief, institution_brief  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402


# ---------------------------------------------------------------------
# 2. Per-request auth context
# ---------------------------------------------------------------------
# Populated by BasicAuthMiddleware before a request reaches the MCP
# handler; read by every tool via require_user(). asyncio.Task copies
# the enclosing contextvars.Context on creation, so this propagates
# correctly through the normal single-request async call chain. If you
# change the SDK's transport internals so that tool dispatch happens on
# a *separate* thread pool without context propagation, thread the user
# through FastMCP's Context/dependency-injection mechanism instead of a
# contextvar.
_current_user: ContextVar[Optional[User]] = ContextVar("_current_user", default=None)


def require_user() -> User:
    user = _current_user.get()
    if user is None:
        # Should be unreachable — BasicAuthMiddleware rejects unauthenticated
        # requests before they reach a tool — but tools must not silently
        # fall back to an unscoped CDBClient() if this ever fires.
        raise PermissionError("No authenticated user bound to this request.")
    return user


def scoped_client() -> CDBClient:
    return CDBClient(user=require_user())


# ---------------------------------------------------------------------
# 3. Basic Auth middleware
# ---------------------------------------------------------------------
# Minimal in-memory throttle: dev-grade brute-force friction only. It is
# per-process and resets on restart, so it does NOT replace a real
# solution for a production, multi-worker deployment — use django-axes
# (or an equivalent account-lockout / rate-limiting package tied to the
# Django DB) there instead.
_FAILURE_WINDOW_S = 60
_MAX_FAILURES = 5
_LOCKOUT_S = 30
_failures: dict[str, list[float]] = {}
_lockouts: dict[str, float] = {}
_lock = threading.Lock()


def _throttled(key: str) -> bool:
    with _lock:
        until = _lockouts.get(key)
        return bool(until and until > time.time())


def _record_failure(key: str) -> None:
    now = time.time()
    with _lock:
        attempts = [t for t in _failures.get(key, []) if now - t < _FAILURE_WINDOW_S]
        attempts.append(now)
        _failures[key] = attempts
        if len(attempts) >= _MAX_FAILURES:
            _lockouts[key] = now + _LOCKOUT_S
            _failures[key] = []


def _record_success(key: str) -> None:
    with _lock:
        _failures.pop(key, None)
        _lockouts.pop(key, None)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """
    Validates HTTP Basic credentials against Django's User model on every
    request, then binds the resulting User for the lifetime of the request
    via the _current_user contextvar. Unauthenticated or invalid
    credentials get a 401 with a WWW-Authenticate challenge and never
    reach the MCP handler or any tool.
    """

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        auth_header = request.headers.get("authorization", "")

        if not auth_header.lower().startswith("basic "):
            return self._challenge("Missing credentials.")

        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            return self._challenge("Malformed Authorization header.")

        if not username or not password:
            return self._challenge("Missing username or password.")

        throttle_key = f"{client_ip}:{username}"
        if _throttled(throttle_key):
            return JSONResponse(
                {"error": "Too many failed attempts. Try again shortly."}, status_code=429
            )

        # Django's authenticate() checks the password against the stored
        # salted hash (PBKDF2 by default) — this file never sees or stores
        # a plaintext-comparable credential beyond this single call.
        user = await self._authenticate(username, password)

        if user is None or not user.is_active:
            _record_failure(throttle_key)
            return self._challenge("Invalid username or password.")

        _record_success(throttle_key)

        token = _current_user.set(user)
        try:
            response = await call_next(request)
        finally:
            _current_user.reset(token)
        return response

    @staticmethod
    async def _authenticate(username: str, password: str) -> Optional[User]:
        # authenticate() hits the DB synchronously; Django's ORM is sync
        # by default, so run it off the event loop the same way any other
        # sync Django call in an ASGI app should be run.
        from asgiref.sync import sync_to_async

        return await sync_to_async(authenticate)(username=username, password=password)

    @staticmethod
    def _challenge(detail: str) -> Response:
        return JSONResponse(
            {"error": detail},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="epiCDB"'},
        )


# ---------------------------------------------------------------------
# 4. MCP server + tools
# ---------------------------------------------------------------------
mcp = FastMCP("epiCDB")


@mcp.tool()
def cdb_whoami() -> dict:
    """Return the authenticated user's username, email, and group memberships."""
    user = require_user()
    return {
        "username": user.username,
        "email": user.email,
        "is_staff": user.is_staff,
        "groups": [g.name for g in user.groups.all()],
    }


@mcp.tool()
def cdb_search(query: str, limit: int = 15) -> dict:
    """
    Cross-domain keyword search over components, physical inventory
    instances, and designs. Returns brief results per domain (id, name,
    and a few identifying fields) — use the *_detail tools for full data
    on a specific hit.
    """
    return scoped_client().search_all(query, limit=limit)


@mcp.tool()
def cdb_where_is(instance_id: str) -> dict:
    """
    Current physical location, institution, and ownership of a single
    inventory item, looked up by its UUID primary key.
    """
    return scoped_client().where_is(instance_id)


@mcp.tool()
def cdb_component_search(query: str, limit: int = 25) -> list[dict]:
    """Search the Component Catalog by name, alternate name, model number, or description."""
    return scoped_client().catalog.search_brief(query, limit=limit)


@mcp.tool()
def cdb_component_summary(component_name: str) -> dict:
    """
    Full detail for a single catalog Component: description, technical
    system, vendors/sources with cost, typed properties, recent log
    entries, and instance count.
    """
    return scoped_client().catalog.summary(component_name)


@mcp.tool()
def cdb_instance_search(query: str, limit: int = 25) -> list[dict]:
    """Search physical inventory instances by tag, serial number, or component name."""
    return scoped_client().inventory.search_brief(query, limit=limit)


@mcp.tool()
def cdb_instance_detail(instance_id: str) -> dict:
    """
    Full detail for a single physical inventory instance, looked up by
    UUID: location, ownership, typed properties, and log history.
    """
    return scoped_client().inventory.detail(instance_id)


@mcp.tool()
def cdb_instances_at_institution(institution_abbreviation: str, limit: int = 25) -> list[dict]:
    """List physical inventory instances currently located at a given institution (e.g. 'BNL')."""
    client = scoped_client()
    return [instance_brief(i) for i in client.inventory.at_institution(institution_abbreviation, limit=limit)]


@mcp.tool()
def cdb_design_search(query: str, limit: int = 25) -> list[dict]:
    """Search the Design Library by name or description."""
    return scoped_client().designs.search_brief(query, limit=limit)


@mcp.tool()
def cdb_design_summary(design_name: str) -> dict:
    """Full detail for a design, including its recursive Bill of Materials."""
    return scoped_client().designs.summary(design_name)


@mcp.tool()
def cdb_design_bom(design_name: str) -> list[dict]:
    """Recursive Bill of Materials for a named design (nested components and sub-designs)."""
    return scoped_client().designs.bom(design_name)


@mcp.tool()
def cdb_list_institutions() -> list[dict]:
    """List all institutions participating in the collaboration (reference data, not scoped)."""
    return [institution_brief(i) for i in scoped_client().locations.all_institutions()]


@mcp.tool()
def cdb_location_tree(institution_abbreviation: str) -> list[dict]:
    """Nested Building -> Room -> Cabinet -> Shelf hierarchy for one institution."""
    return scoped_client().locations.location_tree(institution_abbreviation)


@mcp.tool()
def cdb_systems_overview() -> list[dict]:
    """Technical systems (Tracking, Calorimetry, ...) with component and instance counts."""
    return scoped_client().systems.instance_counts()


@mcp.tool()
def cdb_create_instance(
    component_name: str,
    tag: str = "",
    serial_number: str = "",
    description: str = "",
    location_name: Optional[str] = None,
    owner_group_name: Optional[str] = None,
) -> dict:
    """
    Create a new physical inventory instance of an existing catalog
    Component. The instance is always owned by the authenticated caller;
    owner_group_name must name a group the caller actually belongs to
    (write access to that record is then governed by group_writeable,
    which is set automatically when an owner_group is supplied).
    """
    return scoped_client().inventory.create(
        component_name=component_name,
        tag=tag,
        serial_number=serial_number,
        description=description,
        location_name=location_name,
        owner_group_name=owner_group_name,
    )


# ---------------------------------------------------------------------
# 5. ASGI app: MCP Streamable HTTP wrapped in Basic Auth
# ---------------------------------------------------------------------
# `streamable_http_app()` is the FastMCP method name as of the current
# `mcp` SDK release at time of writing. Verify against your installed
# version — this is the one line most likely to need adjusting after
# `pip install`.
mcp_asgi_app = mcp.streamable_http_app()

app = Starlette(routes=mcp_asgi_app.routes)
app.add_middleware(BasicAuthMiddleware)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
