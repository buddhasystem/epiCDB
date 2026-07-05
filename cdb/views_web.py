"""
CDB web views — server-rendered Django pages.
URL config: cdb/urls_web.py
"""
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Count
from django.core.paginator import Paginator

from .models import (
    Component, ComponentInstance, Design, DesignElement,
    Institution, LogEntry, TechnicalSystem,
)


PAGE_SIZE = 20


# ── helpers ──────────────────────────────────────────────────────────────────

def _qs(request, *exclude):
    """Return current GET params as a query string, minus excluded keys."""
    params = request.GET.copy()
    for key in ('page',) + exclude:
        params.pop(key, None)
    return params.urlencode()


# ── Dashboard ─────────────────────────────────────────────────────────────────

def dashboard(request):
    context = {
        'component_count':   Component.objects.count(),
        'instance_count':    ComponentInstance.objects.count(),
        'design_count':      Design.objects.count(),
        'log_count':         LogEntry.objects.count(),
        'institution_count': Institution.objects.count(),
        'recent_logs':       LogEntry.objects.select_related('logged_by').order_by('-timestamp')[:8],
        'institutions':      Institution.objects.all(),
        'active_page':       'dashboard',
    }
    return render(request, 'cdb/dashboard.html', context)


# ── Component Catalog ─────────────────────────────────────────────────────────

# Valid sort columns for Component table
_COMPONENT_SORT = {
    'name':     'name',
    'model':    'model_number',
    'system':   'technical_system__name',
    'project':  'project',
    'count':    'instance_count',
}

def component_list(request):
    q      = request.GET.get('q', '')
    system = request.GET.get('system', '')
    sort   = request.GET.get('sort', 'name')
    direction = request.GET.get('dir', 'asc')

    qs = Component.objects.select_related(
        'technical_system', 'owner_group',
    ).annotate(instance_count=Count('instances'))

    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(alternate_name__icontains=q) |
            Q(model_number__icontains=q) | Q(description__icontains=q)
        )
    if system:
        qs = qs.filter(technical_system__name=system)

    order_field = _COMPONENT_SORT.get(sort, 'name')
    if direction == 'desc':
        order_field = '-' + order_field
    qs = qs.order_by(order_field)

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'system':      system,
        'systems':     TechnicalSystem.objects.all(),
        'sort':        sort,
        'dir':         direction,
        'query_str':   _qs(request),           # preserves sort/dir, strips page
        'sort_qs':     _qs(request, 'sort', 'dir'),  # strips sort/dir for new sort links
        'active_page': 'components',
    }
    return render(request, 'cdb/components.html', context)


def component_detail(request, pk):
    comp = get_object_or_404(
        Component.objects.prefetch_related(
            'componentsource_set__source',
            'properties__property_type',
            'log_entries__logged_by',
            'instances__location__institution',
        ).select_related('technical_system', 'owner_group', 'owner_user'),
        pk=pk,
    )
    context = {'component': comp, 'active_page': 'components'}
    return render(request, 'cdb/component_detail.html', context)


# ── Component Inventory ───────────────────────────────────────────────────────

# Valid sort columns for ComponentInstance table
_INSTANCE_SORT = {
    'tag':       'tag',
    'component': 'component__name',
    'system':    'technical_system__name',
    'serial':    'serial_number',
    'location':  'location__name',
    'group':     'owner_group__name',
    'owner':     'owner_user__username',
    'created':   'created_on',
}

def inventory_list(request):
    q           = request.GET.get('q', '')
    institution = request.GET.get('institution', '')
    sort        = request.GET.get('sort', 'created')
    direction   = request.GET.get('dir', 'desc')

    qs = ComponentInstance.objects.select_related(
        'component', 'technical_system',
        'location', 'location__institution', 'owner_group', 'owner_user',
    )
    if q:
        qs = qs.filter(
            Q(tag__icontains=q) | Q(serial_number__icontains=q) |
            Q(component__name__icontains=q)
        )
    if institution:
        qs = qs.filter(location__institution__abbreviation=institution)

    order_field = _INSTANCE_SORT.get(sort, 'created_on')
    if direction == 'desc':
        order_field = '-' + order_field
    qs = qs.order_by(order_field)

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':     page_obj,
        'q':            q,
        'institution':  institution,
        'institutions': Institution.objects.all(),
        'sort':         sort,
        'dir':          direction,
        'query_str':    _qs(request),
        'sort_qs':      _qs(request, 'sort', 'dir'),
        'active_page':  'inventory',
    }
    return render(request, 'cdb/inventory.html', context)


def inventory_detail(request, pk):
    instance = get_object_or_404(
        ComponentInstance.objects.prefetch_related(
            'properties__property_type',
            'log_entries__logged_by',
        ).select_related(
            'component', 'location', 'location__institution',
            'owner_group', 'owner_user',
        ),
        pk=pk,
    )
    context = {'instance': instance, 'active_page': 'inventory'}
    return render(request, 'cdb/inventory_detail.html', context)


# ── Designs ───────────────────────────────────────────────────────────────────

def design_list(request):
    q = request.GET.get('q', '')

    qs = Design.objects.select_related('owner_group').annotate(
        element_count=Count('elements')
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'query_str':   _qs(request),
        'active_page': 'designs',
    }
    return render(request, 'cdb/designs.html', context)


def design_detail(request, pk):
    design = get_object_or_404(
        Design.objects.prefetch_related(
            'properties__property_type',
            'log_entries__logged_by',
        ).select_related('owner_group', 'owner_user'),
        pk=pk,
    )
    bom_rows = _build_bom(design)
    context  = {'design': design, 'bom_rows': bom_rows, 'active_page': 'designs'}
    return render(request, 'cdb/design_detail.html', context)


def _build_bom(design, depth=0, max_depth=10):
    """Flat list of BOM rows with depth info for template indentation."""
    rows = []
    if depth > max_depth:
        return rows
    for el in DesignElement.objects.filter(design=design).select_related(
        'component', 'child_design', 'installed_instance'
    ):
        rows.append({
            'element':   el,
            'depth':     depth,
            'indent':    list(range(depth)),   # iterate in template
            'is_design': el.child_design_id is not None,
        })
        if el.child_design:
            rows.extend(_build_bom(el.child_design, depth + 1, max_depth))
    return rows


# ── Technical Systems ─────────────────────────────────────────────────────────

def system_list(request):
    """List all technical systems with component and instance counts."""
    systems = TechnicalSystem.objects.annotate(
        component_count=Count('components', distinct=True),
        instance_count=Count('components__instances', distinct=True),
    ).order_by('name')
    context = {'systems': systems, 'active_page': 'systems'}
    return render(request, 'cdb/systems.html', context)


def system_detail(request, pk):
    """Show a single technical system with its inventory items, filterable."""
    system = get_object_or_404(TechnicalSystem, pk=pk)

    q           = request.GET.get('q', '')
    institution = request.GET.get('institution', '')

    qs = ComponentInstance.objects.filter(
        component__technical_system=system,
    ).select_related(
        'component',
        'location', 'location__institution', 'owner_group',
    )

    if q:
        qs = qs.filter(
            Q(tag__icontains=q) | Q(serial_number__icontains=q) |
            Q(component__name__icontains=q)
        )
    if institution:
        qs = qs.filter(location__institution__abbreviation=institution)
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':     page_obj,
        'q':            q,
        'institution':  institution,
        'institutions': Institution.objects.all(),
        'query_str':    _qs(request),
        'active_page':  'inventory',
    }
    return render(request, 'cdb/inventory.html', context)


def inventory_detail(request, pk):
    instance = get_object_or_404(
        ComponentInstance.objects.prefetch_related(
            'properties__property_type',
            'log_entries__logged_by',
        ).select_related(
            'component', 'location', 'location__institution',
            'owner_group', 'owner_user',
        ),
        pk=pk,
    )
    context = {'instance': instance, 'active_page': 'inventory'}
    return render(request, 'cdb/inventory_detail.html', context)


# ── User Inventory ───────────────────────────────────────────────────────────

def user_inventory(request, username):
    """List all component instances owned by a given user."""
    from django.contrib.auth.models import User as AuthUser
    owner = get_object_or_404(AuthUser, username=username)

    q = request.GET.get('q', '')
    qs = ComponentInstance.objects.filter(owner_user=owner).select_related(
        'component', 'technical_system',
        'location', 'location__institution', 'owner_group', 'owner_user',
    )
    if q:
        qs = qs.filter(
            Q(tag__icontains=q) | Q(serial_number__icontains=q) |
            Q(component__name__icontains=q)
        )

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'owner':       owner,
        'query_str':   _qs(request),
        'active_page': 'inventory',
        'page_title':  f'Items owned by {owner.get_full_name() or owner.username}',
    }
    return render(request, 'cdb/inventory.html', context)


# ── Institutions & Locations ──────────────────────────────────────────────────

def institution_list(request):
    institutions = Institution.objects.prefetch_related(
        'locations',
        'users__user',
    ).all()
    context = {'institutions': institutions, 'active_page': 'institutions'}
    return render(request, 'cdb/institutions.html', context)


# ── Activity Log ──────────────────────────────────────────────────────────────

def log_list(request):
    q     = request.GET.get('q', '')
    topic = request.GET.get('topic', '')

    qs = LogEntry.objects.select_related(
        'logged_by', 'component', 'component_instance', 'design',
    ).order_by('-timestamp')

    if q:
        qs = qs.filter(entry__icontains=q)
    if topic:
        qs = qs.filter(topic=topic)

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'topic':       topic,
        'topics':      LogEntry.TOPIC_CHOICES,
        'query_str':   _qs(request),
        'active_page': 'logs',
    }
    return render(request, 'cdb/logs.html', context)
