"""
CDB web views — server-rendered Django pages.
URL config: cdb/urls_web.py
"""
import io
from itertools import groupby

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import HttpResponseForbidden, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.db.models import Q, Count
from django.core.paginator import Paginator
import qrcode

from .models import (
    Component, ComponentInstance, Design, DesignElement,
    Institution, Location, LogEntry, TechnicalSystem, PropertyType, PropertyValue,
)


PAGE_SIZE = 20

# Selectable page sizes for the Inventory list -- offered via a "per page"
# dropdown next to the pagination controls. Anything else in the ?per_page=
# query param (missing, non-numeric, or not one of these) falls back to
# INVENTORY_DEFAULT_PAGE_SIZE.
INVENTORY_PAGE_SIZE_CHOICES = [10, 25, 50, 100]
INVENTORY_DEFAULT_PAGE_SIZE = 25


# ── helpers ──────────────────────────────────────────────────────────────────

def _qs(request, *exclude):
    """Return current GET params as a query string, minus excluded keys."""
    params = request.GET.copy()
    for key in ('page',) + exclude:
        params.pop(key, None)
    return params.urlencode()


def _inventory_page_size(request):
    """Resolve the Inventory list's page size from ?per_page=, constrained
    to INVENTORY_PAGE_SIZE_CHOICES."""
    try:
        size = int(request.GET.get('per_page', INVENTORY_DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return INVENTORY_DEFAULT_PAGE_SIZE
    return size if size in INVENTORY_PAGE_SIZE_CHOICES else INVENTORY_DEFAULT_PAGE_SIZE


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

    q         = request.GET.get('q', '')
    system    = request.GET.get('system', '')
    group     = request.GET.get('group', '')
    sort      = request.GET.get('sort', '')
    direction = request.GET.get('dir', 'asc')

    qs = Component.objects.select_related(
        'technical_system', 'owner_group', 'owner_user',
    ).annotate(instance_count=Count('instances')).order_by('name')

    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(alternate_name__icontains=q) |
            Q(model_number__icontains=q) | Q(description__icontains=q)
        )
    if system:
        qs = qs.filter(technical_system__name=system)
    if group:
        qs = qs.filter(owner_group__name=group)

    _sort_map = {
        'name':   'name',
        'model':  'model_number',
        'system': 'technical_system__name',
        'count':  'instance_count',
        'group':  'owner_group__name',
        'owner':  'owner_user__username',
    }
    if sort in _sort_map:
        order_field = _sort_map[sort]
        if direction == 'desc':
            order_field = '-' + order_field
        qs = qs.order_by(order_field, 'name')

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'system':      system,
        'group':       group,
        'sort':        sort,
        'dir':         direction,
        'sort_qs':     _qs(request, 'sort', 'dir'),
        'systems':     TechnicalSystem.objects.order_by('name'),
        'groups':      Group.objects.order_by('name'),
        'query_str':   _qs(request),
        'active_page': 'components',
        'form_error':  form_error,
        'form_data':   form_data,
        'open_modal':  bool(form_error),
    }
    return render(request, 'cdb/components.html', context)


@login_required
def component_detail(request, pk):
    """Component detail page. Also handles the "Add Property" pop-up form:
    a POST here (property_type, tag, value, units) creates a component-level
    PropertyValue, which is then inherited by every ComponentInstance of this
    component that doesn't already override that (property_type, tag) pair."""
    comp = get_object_or_404(
        Component.objects.prefetch_related(
            'componentsource_set__source',
            'properties__property_type',
            'log_entries__logged_by',
            'instances__location__institution',
        ).select_related('technical_system', 'owner_group', 'owner_user'),
        pk=pk,
    )

    form_error = None
    form_data  = {}

    if request.method == 'POST':
        property_type_id = request.POST.get('property_type') or None
        tag               = request.POST.get('tag', '').strip()
        value             = request.POST.get('value', '').strip()
        units             = request.POST.get('units', '').strip()
        uploaded_file     = request.FILES.get('file')
        form_data = {'property_type': property_type_id or '', 'tag': tag, 'value': value, 'units': units}

        if not property_type_id:
            form_error = 'Property Type is required.'
        else:
            # (component, property_type, tag) identifies "the same property".
            # Re-submitting the same combination (e.g. re-uploading a
            # replacement datasheet) should update that one row in place,
            # not create a second row that duplicates it in the panel.
            pv, created = PropertyValue.objects.get_or_create(
                component=comp, property_type_id=property_type_id, tag=tag,
                defaults={'value': value, 'units': units, 'file': uploaded_file},
            )
            if not created:
                pv.value = value
                pv.units = units
                if uploaded_file:
                    pv.file = uploaded_file
                pv.save()
            return redirect('component-detail', pk=comp.pk)

    # Distinct sites (institutions) among this component's instances, for the
    # site filter dropdown on the Inventory Instances panel.
    sites = sorted(
        {inst.location.institution for inst in comp.instances.all()
         if inst.location and inst.location.institution},
        key=str,
    )
    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_add_instance = bool(comp.owner_group_id) and comp.owner_group_id in user_group_ids

    # Same group-membership check gates the "Current Owner" transfer
    # control -- only members of the component's owner_group may reassign
    # ownership, and the dropdown only ever lists that group's members.
    can_transfer_owner = can_add_instance or request.user.is_superuser
    group_members = (
        comp.owner_group.user_set.order_by('username') if comp.owner_group_id else User.objects.none()
    )

    # Group the Properties panel by units of measurement (e.g. every "g"
    # property together, every "mm" property together), so related physical
    # properties read as a set instead of being scattered in whatever order
    # they were added. Properties with no units (documents, images, links,
    # unitless text) form their own trailing group. Sort key puts
    # units-bearing groups first (alphabetically by unit), the no-units
    # group last, and orders items within a group by property type name for
    # a stable, predictable layout.
    sorted_props = sorted(
        comp.properties.all(),
        key=lambda pv: (pv.units == '', pv.units, str(pv.property_type)),
    )
    prop_groups = [
        {'units': units, 'items': list(items)}
        for units, items in groupby(sorted_props, key=lambda pv: pv.units)
    ]

    context = {
        'component':        comp,
        'active_page':      'components',
        'sites':            sites,
        'property_types':   PropertyType.objects.order_by('name'),
        'prop_groups':      prop_groups,
        'can_add_instance': can_add_instance,
        'can_transfer_owner': can_transfer_owner,
        'group_members':    group_members,
        'locations':        Location.objects.select_related('institution').order_by('name'),
        'form_error':      form_error,
        'form_data':       form_data,
        'open_modal':      bool(form_error),
    }
    return render(request, 'cdb/component_detail.html', context)


@login_required
def component_property_delete(request, pk, property_id):
    """Remove a property from a component's Properties panel.
    property_id is scoped to component=pk so a property can only be deleted
    through the component it actually belongs to. If the property has an
    attached file, it's removed from storage too -- Django does not delete
    the underlying file automatically when a FileField-holding row is
    deleted, so leaving this out would silently orphan files on disk."""
    comp = get_object_or_404(Component, pk=pk)
    pv = get_object_or_404(PropertyValue, pk=property_id, component=comp)
    if request.method == 'POST':
        if pv.file:
            pv.file.delete(save=False)
        pv.delete()
    return redirect('component-detail', pk=comp.pk)


@login_required
def component_property_update(request, pk, property_id):
    """Inline-edit a component property's value/units from the Properties
    panel. property_id is scoped to component=pk, same protection as
    component_property_delete. Document/Image property types (and any
    property that happens to have a file attached) are excluded -- their
    content is managed via file upload in the Add Property modal, not a
    plain text field, so an edit attempt on one of those is silently
    ignored rather than honoured."""
    comp = get_object_or_404(Component, pk=pk)
    pv = get_object_or_404(PropertyValue, pk=property_id, component=comp)
    if request.method == 'POST' and pv.property_type.handler not in ('document', 'image') and not pv.file:
        pv.value = request.POST.get('value', '').strip()
        pv.units = request.POST.get('units', '').strip()
        pv.save()
    return redirect('component-detail', pk=comp.pk)


@login_required
def component_instance_create(request, pk):
    """Create a new ComponentInstance for this component from the "+ Add
    Instance" button on the component detail page, and send the user
    straight to the new instance's page. Only members of the component's
    owner_group may do this. The button is hidden from everyone else, but
    this is the authoritative, server-side check -- a POST here from
    anyone else (or against a component with no owner_group at all to
    check membership against) is rejected with 403 rather than silently
    creating an instance owned by a group the requester doesn't belong
    to."""
    comp = get_object_or_404(Component, pk=pk)
    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_add = bool(comp.owner_group_id) and comp.owner_group_id in user_group_ids

    if request.method == 'POST':
        if not can_add:
            return HttpResponseForbidden("You don't have permission to add instances of this component.")
        tag           = request.POST.get('tag', '').strip()
        serial_number = request.POST.get('serial_number', '').strip()
        location_id   = request.POST.get('location') or None
        instance = ComponentInstance.objects.create(
            tag=tag,
            serial_number=serial_number,
            component=comp,
            location_id=location_id,
            owner_group=comp.owner_group,
            owner_user=request.user,
            created_by=request.user,
        )
        return redirect('inventory-detail', pk=instance.pk)

    return redirect('component-detail', pk=comp.pk)


@login_required
def component_transfer_owner(request, pk):
    """Transfer a component's ownership to another member of its own
    owner_group, from the "Current Owner" control on the component detail
    page. Only members of the component's owner_group may initiate a
    transfer -- same authorization pattern as component_instance_create,
    enforced with 403 on an unauthorized POST, not just hidden client-side.

    The new owner must themselves belong to the component's owner_group --
    the dropdown only ever offers group members, but a POST naming someone
    outside the group is a business-rule violation from an otherwise
    authorized user, not an authorization breach, so it's silently ignored
    (component redirects unchanged) rather than rejected with 403."""
    comp = get_object_or_404(Component, pk=pk)
    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_transfer = (
        (bool(comp.owner_group_id) and comp.owner_group_id in user_group_ids)
        or request.user.is_superuser
    )

    if request.method == 'POST':
        if not can_transfer:
            return HttpResponseForbidden("You don't have permission to change this component's owner.")
        new_owner_id = request.POST.get('owner_user') or None
        if new_owner_id and User.objects.filter(pk=new_owner_id, groups=comp.owner_group_id).exists():
            comp.owner_user_id = new_owner_id
            comp.save()

    return redirect('component-detail', pk=comp.pk)


# ── Component Inventory ───────────────────────────────────────────────────────

@login_required
def inventory_list(request):
    """List/search the inventory. Also handles the "Add Inventory Item"
    pop-up form: a POST here (component, tag, serial number, location,
    group) creates a ComponentInstance and redirects to its detail page.
    The owner is always the logged-in user, and the group dropdown is
    restricted to groups that user actually belongs to. On validation
    failure the list re-renders with the modal reopened and the entered
    values kept."""
    form_error = None
    form_data  = {}

    if request.method == 'POST':
        tag           = request.POST.get('tag', '').strip()
        serial_number = request.POST.get('serial_number', '').strip()
        component_id  = request.POST.get('component') or None
        location_id   = request.POST.get('location') or None
        group_id      = request.POST.get('owner_group') or None
        form_data = {
            'tag':           tag,
            'serial_number': serial_number,
            'component':     component_id or '',
            'location':      location_id or '',
            'owner_group':   group_id or '',
        }

        user_group_ids = set(request.user.groups.values_list('id', flat=True))

        if not component_id:
            form_error = 'Please choose a component.'
        elif not Component.objects.filter(pk=component_id).exists():
            form_error = 'Please choose a valid component.'
        elif group_id and int(group_id) not in user_group_ids:
            form_error = 'You can only assign a group you belong to.'
        else:
            instance = ComponentInstance.objects.create(
                tag=tag,
                serial_number=serial_number,
                component_id=component_id,
                location_id=location_id,
                owner_group_id=group_id,
                owner_user=request.user,
                created_by=request.user,
            )
            return redirect('inventory-detail', pk=instance.pk)

    q           = request.GET.get('q', '')
    location    = request.GET.get('location', '')
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
    if location:
        qs = qs.filter(location_id=location)
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

    per_page  = _inventory_page_size(request)
    paginator = Paginator(qs, per_page)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':     page_obj,
        'q':            q,
        'location':     location,
        'system':       system,
        'group':        group,
        'owner':        owner,
        'sort':         sort,
        'dir':          direction,
        'sort_qs':      sort_qs,
        'per_page':         per_page,
        'per_page_choices': INVENTORY_PAGE_SIZE_CHOICES,
        'systems':      TechnicalSystem.objects.order_by('name'),
        'groups':       Group.objects.order_by('name'),
        'users':        User.objects.order_by('username'),
        'query_str':    _qs(request),
        'active_page':  'inventory',
        'components':      Component.objects.order_by('name'),
        'locations':       Location.objects.select_related('institution').order_by('name'),
        'user_groups':     request.user.groups.order_by('name'),
        'show_add_button': True,
        'form_error':      form_error,
        'form_data':       form_data,
        'open_modal':      bool(form_error),
    }
    return render(request, 'cdb/inventory.html', context)


@login_required
def inventory_property_update(request, pk, property_id):
    """Inline-edit a property's value/units from the instance detail page.
    property_id may refer to either an instance-owned PropertyValue or one
    inherited from the instance's Component (as returned by
    effective_properties()) -- scoped to one or the other so an unrelated
    property can't be targeted by guessing an id.

    Editing an instance-owned row updates it in place. Editing an inherited
    row does NOT mutate the shared component-level default (that would
    silently change the value for every other instance); instead it
    creates (or updates) this instance's own override for the same
    (property_type, tag) pair -- the same effect as using the "Add /
    Override" form with a matching Property Type and Tag.

    Document/Image property types (and any property that happens to have a
    file attached) are excluded, same as the component-level version of
    this feature."""
    instance = get_object_or_404(ComponentInstance, pk=pk)
    pv = get_object_or_404(
        PropertyValue,
        Q(component_instance=instance) | Q(component_id=instance.component_id),
        pk=property_id,
    )
    if request.method == 'POST' and pv.property_type.handler not in ('document', 'image') and not pv.file:
        value = request.POST.get('value', '').strip()
        units = request.POST.get('units', '').strip()
        if pv.component_instance_id == instance.pk:
            pv.value = value
            pv.units = units
            pv.save()
        else:
            override, created = PropertyValue.objects.get_or_create(
                component_instance=instance, property_type_id=pv.property_type_id, tag=pv.tag,
                defaults={'value': value, 'units': units},
            )
            if not created:
                override.value = value
                override.units = units
                override.save()
    return redirect('inventory-detail', pk=instance.pk)


@login_required
def inventory_detail(request, pk):
    """Instance detail page. Also handles the "Add / Override Property"
    pop-up form: a POST here (property_type, tag, value, units) creates an
    instance-level PropertyValue. If its (property_type, tag) matches one
    inherited from the component, it overrides (hides) that default; if not,
    it's simply an additional property on this instance alone. See
    ComponentInstance.effective_properties()."""
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

    form_error = None
    form_data  = {}

    if request.method == 'POST':
        property_type_id = request.POST.get('property_type') or None
        tag               = request.POST.get('tag', '').strip()
        value             = request.POST.get('value', '').strip()
        units             = request.POST.get('units', '').strip()
        uploaded_file     = request.FILES.get('file')
        form_data = {'property_type': property_type_id or '', 'tag': tag, 'value': value, 'units': units}

        if not property_type_id:
            form_error = 'Property Type is required.'
        else:
            # Same reasoning as component_detail: (component_instance,
            # property_type, tag) identifies "the same property" -- update
            # it in place on resubmission instead of creating a duplicate.
            pv, created = PropertyValue.objects.get_or_create(
                component_instance=instance, property_type_id=property_type_id, tag=tag,
                defaults={'value': value, 'units': units, 'file': uploaded_file},
            )
            if not created:
                pv.value = value
                pv.units = units
                if uploaded_file:
                    pv.file = uploaded_file
                pv.save()
            return redirect('inventory-detail', pk=instance.pk)

    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_transfer_owner = (
        (bool(instance.owner_group_id) and instance.owner_group_id in user_group_ids)
        or request.user.is_superuser
    )
    group_members = (
        instance.owner_group.user_set.order_by('username') if instance.owner_group_id else User.objects.none()
    )

    context = {
        'instance':            instance,
        'active_page':         'inventory',
        'property_types':      PropertyType.objects.order_by('name'),
        'can_transfer_owner':  can_transfer_owner,
        'group_members':       group_members,
        'institutions':        Institution.objects.order_by('name'),
        'locations':            Location.objects.select_related('institution').order_by('name'),
        'form_error':      form_error,
        'form_data':       form_data,
        'open_modal':      bool(form_error),
    }
    return render(request, 'cdb/inventory_detail.html', context)


@login_required
def inventory_update_location(request, pk):
    """Move a ComponentInstance to a different Location, from the
    Institution/Location controls on the instance detail page. Gated by
    the same group-membership-or-superuser check as ownership transfer.
    The Institution dropdown is only a client-side filter over the
    Location list -- Location already carries its own institution FK, so
    the server only needs to persist the submitted location; there's no
    way to end up with an institution/location pair that disagree with
    each other since every option in the list is a real, existing
    Location row with its own correct institution."""
    instance = get_object_or_404(ComponentInstance, pk=pk)
    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_manage = (
        (bool(instance.owner_group_id) and instance.owner_group_id in user_group_ids)
        or request.user.is_superuser
    )

    if request.method == 'POST':
        if not can_manage:
            return HttpResponseForbidden("You don't have permission to move this instance.")
        location_id = request.POST.get('location') or None
        if location_id:
            if Location.objects.filter(pk=location_id).exists():
                instance.location_id = location_id
                instance.save()
        else:
            instance.location_id = None
            instance.save()

    return redirect('inventory-detail', pk=instance.pk)


@login_required
def inventory_transfer_owner(request, pk):
    """Transfer a ComponentInstance's ownership to another member of its own
    owner_group, from the "Current Owner" control on the instance detail
    page. Same pattern as component_transfer_owner: group members (or any
    superuser) may initiate a transfer, enforced server-side with 403 on an
    unauthorized POST; a target user outside the owner_group is a
    business-rule violation from an otherwise authorized user, not an
    authorization breach, so it's silently ignored rather than rejected."""
    instance = get_object_or_404(ComponentInstance, pk=pk)
    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_transfer = (
        (bool(instance.owner_group_id) and instance.owner_group_id in user_group_ids)
        or request.user.is_superuser
    )

    if request.method == 'POST':
        if not can_transfer:
            return HttpResponseForbidden("You don't have permission to change this instance's owner.")
        new_owner_id = request.POST.get('owner_user') or None
        if new_owner_id and User.objects.filter(pk=new_owner_id, groups=instance.owner_group_id).exists():
            instance.owner_user_id = new_owner_id
            instance.save()

    return redirect('inventory-detail', pk=instance.pk)


@login_required
def inventory_qr(request, pk):
    """PNG QR code encoding this instance's ID, for the "QR" pop-up on the
    instance detail page. Generated server-side with the `qrcode` package
    (pure Python + Pillow) -- no network calls, no client-side JS library,
    so it works the same whether or not the deployment has outbound
    internet access."""
    instance = get_object_or_404(ComponentInstance, pk=pk)
    img = qrcode.make(str(instance.pk), box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return HttpResponse(buf.getvalue(), content_type='image/png')


# ── Designs ───────────────────────────────────────────────────────────────────

@login_required
def design_list(request):
    q         = request.GET.get('q', '')
    group     = request.GET.get('group', '')
    owner     = request.GET.get('owner', '')
    sort      = request.GET.get('sort', '')
    direction = request.GET.get('dir', 'asc')

    qs = Design.objects.select_related('owner_group', 'owner_user').annotate(
        element_count=Count('elements')
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if group:
        qs = qs.filter(owner_group__name=group)
    if owner:
        qs = qs.filter(owner_user__username=owner)

    _sort_map = {
        'name':  'name',
        'count': 'element_count',
        'group': 'owner_group__name',
        'owner': 'owner_user__username',
    }
    if sort in _sort_map:
        order_field = _sort_map[sort]
        if direction == 'desc':
            order_field = '-' + order_field
        qs = qs.order_by(order_field, 'name')
    else:
        qs = qs.order_by('name')

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':    page_obj,
        'q':           q,
        'group':       group,
        'owner':       owner,
        'sort':        sort,
        'dir':         direction,
        'sort_qs':     _qs(request, 'sort', 'dir'),
        'groups':      Group.objects.order_by('name'),
        'users':       User.objects.order_by('username'),
        'query_str':   _qs(request),
        'active_page': 'designs',
    }
    return render(request, 'cdb/designs.html', context)


@login_required
def design_detail(request, pk):
    """Design detail page. Also handles the "Add Property" pop-up form:
    a POST here (property_type, tag, value, units) creates a design-level
    PropertyValue. Only members of the design's owner_group may add a
    property -- the button is hidden from everyone else, and a POST from
    anyone else is rejected with 403 (same authorization pattern as
    component_instance_create)."""
    design = get_object_or_404(
        Design.objects.prefetch_related(
            'properties__property_type',
            'log_entries__logged_by',
        ).select_related('owner_group', 'owner_user'),
        pk=pk,
    )

    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_add_property = bool(design.owner_group_id) and design.owner_group_id in user_group_ids

    form_error = None
    form_data  = {}

    if request.method == 'POST':
        if not can_add_property:
            return HttpResponseForbidden("You don't have permission to add properties to this design.")
        property_type_id = request.POST.get('property_type') or None
        tag               = request.POST.get('tag', '').strip()
        value             = request.POST.get('value', '').strip()
        units             = request.POST.get('units', '').strip()
        uploaded_file     = request.FILES.get('file')
        form_data = {'property_type': property_type_id or '', 'tag': tag, 'value': value, 'units': units}

        if not property_type_id:
            form_error = 'Property Type is required.'
        else:
            pv, created = PropertyValue.objects.get_or_create(
                design=design, property_type_id=property_type_id, tag=tag,
                defaults={'value': value, 'units': units, 'file': uploaded_file},
            )
            if not created:
                pv.value = value
                pv.units = units
                if uploaded_file:
                    pv.file = uploaded_file
                pv.save()
            return redirect('design-detail', pk=design.pk)

    bom_rows = _build_bom(design)
    context  = {
        'design':            design,
        'bom_rows':          bom_rows,
        'active_page':       'designs',
        'can_add_property':  can_add_property,
        'property_types':    PropertyType.objects.order_by('name'),
        'form_error':        form_error,
        'form_data':         form_data,
        'open_modal':        bool(form_error),
    }
    return render(request, 'cdb/design_detail.html', context)


@login_required
def design_property_update(request, pk, property_id):
    """Inline-edit a design property's value/units from the Properties
    panel. property_id is scoped to design=pk. Only members of the
    design's owner_group may edit -- same authorization check as adding a
    property; a POST from anyone else is rejected with 403. Document/Image
    property types (and any property that happens to have a file attached)
    are excluded from editing regardless of group membership, same as the
    component-level version of this feature."""
    design = get_object_or_404(Design, pk=pk)
    pv = get_object_or_404(PropertyValue, pk=property_id, design=design)

    user_group_ids = set(request.user.groups.values_list('id', flat=True))
    can_edit = bool(design.owner_group_id) and design.owner_group_id in user_group_ids

    if request.method == 'POST':
        if not can_edit:
            return HttpResponseForbidden("You don't have permission to edit properties of this design.")
        if pv.property_type.handler not in ('document', 'image') and not pv.file:
            pv.value = request.POST.get('value', '').strip()
            pv.units = request.POST.get('units', '').strip()
            pv.save()
    return redirect('design-detail', pk=design.pk)


def _build_bom(design, depth=0, max_depth=10):
    """Flat list of BOM rows with depth info for template indentation.

    Each row carries a 'row_type' of 'child_design' (the element points at
    another Design), 'instance' (a component element with a specific
    inventory instance installed), or 'component' (a plain catalog
    placeholder with no instance installed yet) -- this drives the Type
    and Tag columns in the BOM table."""
    rows = []
    if depth > max_depth:
        return rows
    for el in DesignElement.objects.filter(design=design).select_related(
        'component', 'child_design', 'installed_instance'
    ):
        if el.child_design_id is not None:
            row_type = 'child_design'
        elif el.installed_instance_id is not None:
            row_type = 'instance'
        else:
            row_type = 'component'
        rows.append({
            'element':   el,
            'depth':     depth,
            'indent':    list(range(depth)),   # iterate in template
            'is_design': el.child_design_id is not None,
            'row_type':  row_type,
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
    location    = request.GET.get('location', '')
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
    if location:
        qs = qs.filter(location_id=location)
    if group:
        qs = qs.filter(owner_group__name=group)
    if owner:
        qs = qs.filter(owner_user__username=owner)
    per_page  = _inventory_page_size(request)
    paginator = Paginator(qs, per_page)
    page_obj  = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':     page_obj,
        'q':            q,
        'location':     location,
        'system':       system.name,
        'group':        group,
        'owner':        owner,
        'per_page':         per_page,
        'per_page_choices': INVENTORY_PAGE_SIZE_CHOICES,
        'page_title':   'Inventory — ' + system.name,
        'locations':    Location.objects.select_related('institution').order_by('name'),
        'systems':      TechnicalSystem.objects.order_by('name'),
        'groups':       Group.objects.order_by('name'),
        'users':        User.objects.order_by('username'),
        'query_str':    _qs(request),
        'active_page':  'inventory',
    }
    return render(request, 'cdb/inventory.html', context)


# ── Users ─────────────────────────────────────────────────────────────────────

@login_required
def user_list(request):
    """List all site users (excluding the built-in "admin" account) with
    their name, home institution, and email. Optionally filtered down to
    one group via ?group=<name> and/or one institution via
    ?institution=<abbreviation>, and sortable by Last Name or Institution
    via ?sort=last_name|institution&dir=asc|desc."""
    group        = request.GET.get('group', '')
    institution  = request.GET.get('institution', '')
    sort         = request.GET.get('sort', '')
    direction    = request.GET.get('dir', 'asc')

    users = User.objects.exclude(username='admin').select_related(
        'profile__institution',
    ).prefetch_related('groups')
    if group:
        users = users.filter(groups__name=group)
    if institution:
        users = users.filter(profile__institution__abbreviation=institution)

    _sort_map = {
        'last_name':   'last_name',
        'institution': 'profile__institution__name',
    }
    if sort in _sort_map:
        order_field = _sort_map[sort]
        if direction == 'desc':
            order_field = '-' + order_field
        users = users.order_by(order_field, 'first_name', 'username')
    else:
        users = users.order_by('first_name', 'last_name', 'username')

    context = {
        'users':        users,
        'groups':       Group.objects.order_by('name'),
        'group':        group,
        'institutions': Institution.objects.order_by('name'),
        'institution':  institution,
        'sort':         sort,
        'dir':          direction,
        'sort_qs':      _qs(request, 'sort', 'dir'),
        'active_page':  'users',
    }
    return render(request, 'cdb/users.html', context)


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

    system    = request.GET.get('system', '')
    group     = request.GET.get('group', '')
    sort      = request.GET.get('sort', '')
    direction = request.GET.get('dir', 'asc')

    instances = ComponentInstance.objects.filter(
        location=location,
    ).select_related(
        'component', 'technical_system', 'owner_group', 'owner_user',
    )
    if system:
        instances = instances.filter(technical_system__name=system)
    if group:
        instances = instances.filter(owner_group__name=group)

    # Every column but ID is sortable, same convention as inventory_list.
    _sort_map = {
        'tag':       'tag',
        'component': 'component__name',
        'system':    'technical_system__name',
        'serial':    'serial_number',
        'owner':     'owner_user__username',
        'group':     'owner_group__name',
    }
    if sort in _sort_map:
        order_field = _sort_map[sort]
        if direction == 'desc':
            order_field = '-' + order_field
        instances = instances.order_by(order_field, 'component__name', 'tag')
    else:
        instances = instances.order_by('component__name', 'tag')

    context = {
        'location':    location,
        'instances':   instances,
        'system':      system,
        'group':       group,
        'sort':        sort,
        'dir':         direction,
        'sort_qs':     _qs(request, 'sort', 'dir'),
        'systems':     TechnicalSystem.objects.order_by('name'),
        'groups':      Group.objects.order_by('name'),
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
