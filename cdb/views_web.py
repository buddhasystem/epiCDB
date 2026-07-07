"""
CDB web views — server-rendered Django pages.
URL config: cdb/urls_web.py
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.db.models import Q, Count
from django.core.paginator import Paginator

from .models import (
    Component, ComponentInstance, Design, DesignElement,
    Institution, Location, LogEntry, TechnicalSystem,
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

@login_required
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

@login_required
def component_list(request):
    """List/search the component catalog. Also handles the "New Component"
    pop-up form: a POST here (name, alternate_name, model_number,
    technical_system -- the same fields shown in the table) creates a
    Component and redirects to its detail page. On validation failure the
    list re-renders with the modal reopened and the entered values kept."""
    form_error = None
    form_data  = {}

    if request.method == 'POST':
        name                 = request.POST.get('name', '').strip()
        alternate_name       = request.POST.get('alternate_name', '').strip()
        model_number         = request.POST.get('model_number', '').strip()
        technical_system_id  = request.POST.get('technical_system') or None
        form_data = {
            'name':             name,
            'alternate_name':   alternate_name,
            'model_number':     model_number,
            'technical_system': technical_system_id or '',
        }

        if not name:
            form_error = 'Name is required.'
        elif Component.objects.filter(name=name, project='ePIC').exists():
            form_error = f'A component named "{name}" already exists.'
        else:
            comp = Component.objects.create(
                name=name,
                alternate_name=alternate_name,
                model_number=model_number,
                technical_system_id=technical_system_id,
                owner_user=request.user,
                created_by=request.user,
            )
            return redirect('component-detail', pk=comp.pk)

    q      = request.GET.get('q', '')
    system = request.GET.get('system', '')

    qs = Component.objects.select_related(
        'technical_system', 'owner_group',
    ).annotate(instance_count=Count('instances')).order_by('name')

    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(alternate_name__icontains=q) |
            Q(model_number__icontains=q) | Q(description__icontains=q)
        )
    if system:
        qs = qs.filter(technical_system__name=system)

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'system':      system,
        'systems':     TechnicalSystem.objects.order_by('name'),
        'query_str':   _qs(request),
        'active_page': 'components',
        'form_error':  form_error,
        'form_data':   form_data,
        'open_modal':  bool(form_error),
    }
    return render(request, 'cdb/components.html', context)


@login_required
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

@login_required
def inventory_list(request):
    q           = request.GET.get('q', '')
    institution = request.GET.get('institution', '')
    system      = request.GET.get('system', '')
    group       = request.GET.get('group', '')
    owner       = request.GET.get('owner', '')
    sort        = request.GET.get('sort', 'component')
    direction   = request.GET.get('dir', 'asc')

    qs = ComponentInstance.objects.select_related(
        'component', 'component__technical_system',
        'location', 'location__institution', 'owner_group', 'owner_user',
    )
    if q:
        qs = qs.filter(
            Q(tag__icontains=q) |
            Q(serial_number__icontains=q) | Q(component__name__icontains=q)
        )
    if institution:
        qs = qs.filter(location__institution__abbreviation=institution)
    if system:
        qs = qs.filter(component__technical_system__name=system)
    if group:
        qs = qs.filter(owner_group__name=group)
    if owner:
        qs = qs.filter(owner_user__username=owner)

    _sort_map = {
        'tag':       'tag',
        'component': 'component__name',
        'system':    'component__technical_system__name',
        'serial':    'serial_number',
        'location':  'location__name',
        'group':     'owner_group__name',
        'owner':     'owner_user__username',
        'created':   'created_on',
    }
    order_field = _sort_map.get(sort, 'component__name')
    if direction == 'desc':
        order_field = '-' + order_field
    qs = qs.order_by(order_field)

    _excl   = {'sort', 'dir', 'page'}
    sort_qs = '&'.join(
        f'{k}={v}' for k, v in request.GET.items() if k not in _excl
    )

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':     page_obj,
        'q':            q,
        'institution':  institution,
        'system':       system,
        'group':        group,
        'owner':        owner,
        'sort':         sort,
        'dir':          direction,
        'sort_qs':      sort_qs,
        'institutions': Institution.objects.all(),
        'systems':      TechnicalSystem.objects.order_by('name'),
        'groups':       Group.objects.order_by('name'),
        'users':        User.objects.order_by('username'),
        'query_str':    _qs(request),
        'active_page':  'inventory',
    }
    return render(request, 'cdb/inventory.html', context)


@login_required
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

@login_required
def design_list(request):
    q = request.GET.get('q', '')

    qs = Design.objects.select_related('owner_group').annotate(
        element_count=Count('elements')
    ).order_by('name')
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


@login_required
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

@login_required
def system_list(request):
    """List all technical systems with component and instance counts."""
    systems = TechnicalSystem.objects.select_related('group').annotate(
        component_count=Count('components', distinct=True),
        instance_count=Count('components__instances', distinct=True),
    ).order_by('name')
    context = {'systems': systems, 'active_page': 'systems'}
    return render(request, 'cdb/systems.html', context)


@login_required
def system_detail(request, pk):
    """Show a single technical system with its inventory items, filterable."""
    system = get_object_or_404(TechnicalSystem, pk=pk)

    # The "System" dropdown in inventory.html posts back to this same URL
    # via GET. Since the system itself is chosen via the URL's <pk>, not a
    # query param, switching the dropdown has to redirect to the newly
    # selected system's own detail page (preserving the other filters)
    # rather than silently being ignored.
    selected_name = request.GET.get('system', '')
    if selected_name and selected_name != system.name:
        other = TechnicalSystem.objects.filter(name=selected_name).first()
        if other:
            params = request.GET.copy()
            params.pop('system', None)
            params.pop('page', None)
            query = params.urlencode()
            url = reverse('system-detail', args=[other.pk])
            if query:
                url = f'{url}?{query}'
            return redirect(url)

    q           = request.GET.get('q', '')
    institution = request.GET.get('institution', '')
    group       = request.GET.get('group', '')
    owner       = request.GET.get('owner', '')

    qs = ComponentInstance.objects.filter(
        component__technical_system=system,
    ).select_related(
        'component',
        'location', 'location__institution', 'owner_group',
    )

    if q:
        qs = qs.filter(
            Q(tag__icontains=q) |
            Q(serial_number__icontains=q) | Q(component__name__icontains=q)
        )
    if institution:
        qs = qs.filter(location__institution__abbreviation=institution)
    if group:
        qs = qs.filter(owner_group__name=group)
    if owner:
        qs = qs.filter(owner_user__username=owner)
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':     page_obj,
        'q':            q,
        'institution':  institution,
        'system':       system.name,
        'group':        group,
        'owner':        owner,
        'page_title':   'Inventory — ' + system.name,
        'institutions': Institution.objects.all(),
        'systems':      TechnicalSystem.objects.order_by('name'),
        'groups':       Group.objects.order_by('name'),
        'users':        User.objects.order_by('username'),
        'query_str':    _qs(request),
        'active_page':  'inventory',
    }
    return render(request, 'cdb/inventory.html', context)



# ── Institutions & Locations ──────────────────────────────────────────────────

@login_required
def institution_list(request):
    institutions = Institution.objects.prefetch_related(
        'locations',
        'users__user',
    ).all()
    context = {'institutions': institutions, 'active_page': 'institutions'}
    return render(request, 'cdb/institutions.html', context)


@login_required
def user_inventory(request, username):
    user = get_object_or_404(User, username=username)
    instances = ComponentInstance.objects.filter(
        owner_user=user,
    ).select_related(
        'component', 'technical_system',
        'location', 'location__institution',
        'owner_group',
    ).order_by('component__name', 'tag')

    context = {
        'owner':     user,
        'instances': instances,
        'active_page': 'inventory',
    }
    return render(request, 'cdb/user_inventory.html', context)


@login_required
def location_inventory(request, pk):
    location = get_object_or_404(
        Location.objects.select_related('institution', 'parent'),
        pk=pk,
    )
    instances = ComponentInstance.objects.filter(
        location=location,
    ).select_related(
        'component', 'technical_system', 'owner_group', 'owner_user',
    ).order_by('component__name', 'tag')

    context = {
        'location':  location,
        'instances': instances,
        'active_page': 'institutions',
    }
    return render(request, 'cdb/location_inventory.html', context)


# ── Activity Log ──────────────────────────────────────────────────────────────

@login_required
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
