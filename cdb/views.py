"""
CDB REST API views.

Endpoint map
────────────
GET /api/groups/                         list groups
GET /api/groups/<id>/

GET /api/institutions/                   list institutions
GET /api/locations/                      list all locations (filter: type, institution)
GET /api/locations/<id>/
GET /api/locations/<id>/children/        direct children of a location
GET /api/locations/<id>/instances/       inventory items at this location (and descendants)

GET /api/components/                     catalog list  (filter: technical_system, project)
GET /api/components/<id>/
GET /api/components/<id>/instances/      all physical instances of this component
GET /api/components/<id>/designs/        designs that include this component

GET /api/inventory/                      all instances (filter: tag, component, location)
GET /api/inventory/<id>/
GET /api/designs/                        all designs  (filter: project, owner_group)
GET /api/designs/<id>/
GET /api/designs/<id>/bom/               Bill-of-Materials (walks sub-designs recursively)

GET /api/property-types/                 (filter: category, handler)
GET /api/logs/                           all log entries (filter: topic, component, instance, design)

Note: all endpoints require djangorestframework to be installed.
      pip install djangorestframework
"""

try:
    from django.db.models import Q
    from rest_framework import generics, filters
    from rest_framework.decorators import api_view
    from rest_framework.response import Response
    from rest_framework.reverse import reverse

    from django.contrib.auth.models import Group
    from .models import (
        Institution, Location, PropertyType, LogEntry,
        Component, ComponentInstance, Design, DesignElement,
    )
    from .serializers import (
        GroupSerializer,
        InstitutionSerializer,
        LocationSerializer, LocationListSerializer,
        PropertyTypeSerializer, LogEntrySerializer,
        ComponentSerializer, ComponentListSerializer,
        ComponentInstanceSerializer, ComponentInstanceListSerializer,
        DesignSerializer, DesignListSerializer,
        DesignElementSerializer,
    )

    # ── API root ─────────────────────────────────────────────────────────────

    @api_view(["GET"])
    def api_root(request, format=None):
        return Response({
            "groups":         reverse("group-list",        request=request),
            "institutions":   reverse("institution-list",  request=request),
            "locations":      reverse("location-list",     request=request),
            "components":     reverse("component-list",    request=request),
            "inventory":      reverse("instance-list",     request=request),
            "designs":        reverse("design-list",       request=request),
            "property_types": reverse("propertytype-list", request=request),
            "logs":           reverse("log-list",          request=request),
        })

    # ── Groups ────────────────────────────────────────────────────────────────

    class GroupListView(generics.ListAPIView):
        queryset         = Group.objects.all()
        serializer_class = GroupSerializer
        filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
        search_fields    = ["name", "description"]
        ordering_fields  = ["name"]

    class GroupDetailView(generics.RetrieveAPIView):
        queryset         = Group.objects.all()
        serializer_class = GroupSerializer

    # ── Institutions ──────────────────────────────────────────────────────────

    class InstitutionListView(generics.ListAPIView):
        serializer_class = InstitutionSerializer
        filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
        search_fields    = ["name", "abbreviation", "city", "country"]
        ordering_fields  = ["name", "country"]

        def get_queryset(self):
            qs = Institution.objects.all()
            country = self.request.query_params.get("country")
            if country:
                qs = qs.filter(country__icontains=country)
            return qs

    # ── Locations ─────────────────────────────────────────────────────────────

    class LocationListView(generics.ListAPIView):
        serializer_class = LocationListSerializer
        filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
        search_fields    = ["name", "description"]
        ordering_fields  = ["name", "location_type"]

        def get_queryset(self):
            qs = Location.objects.select_related("institution", "parent").all()
            loc_type = self.request.query_params.get("type")
            inst     = self.request.query_params.get("institution")
            if loc_type:
                qs = qs.filter(location_type=loc_type)
            if inst:
                qs = qs.filter(institution__abbreviation__iexact=inst)
            return qs

    class LocationDetailView(generics.RetrieveAPIView):
        queryset         = Location.objects.select_related("institution", "parent").all()
        serializer_class = LocationSerializer

    class LocationChildrenView(generics.ListAPIView):
        serializer_class = LocationListSerializer

        def get_queryset(self):
            return Location.objects.filter(
                parent_id=self.kwargs["pk"]
            ).select_related("institution")

    class LocationInstancesView(generics.ListAPIView):
        """Inventory items at this location or any of its descendants."""
        serializer_class = ComponentInstanceListSerializer

        def get_queryset(self):
            loc_ids = _descendants(self.kwargs["pk"], include_self=True)
            return ComponentInstance.objects.filter(
                location_id__in=loc_ids
            ).select_related("component", "location", "owner_group")

    # ── Component Catalog ─────────────────────────────────────────────────────

    class ComponentListView(generics.ListAPIView):
        serializer_class = ComponentListSerializer
        filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
        search_fields    = ["name", "alternate_name", "model_number", "description"]
        ordering_fields  = ["name", "model_number", "project"]

        def get_queryset(self):
            qs = Component.objects.select_related(
                "technical_system", "owner_group"
            ).all()
            for param, field in [
                ("technical_system", "technical_system__name__iexact"),
                ("project",          "project__iexact"),
                ("owner_group",      "owner_group__name__iexact"),
            ]:
                val = self.request.query_params.get(param)
                if val:
                    qs = qs.filter(**{field: val})
            return qs

    class ComponentDetailView(generics.RetrieveAPIView):
        queryset = Component.objects.prefetch_related(
            "componentsource_set__source",
            "properties__property_type",
            "log_entries",
        ).select_related("technical_system", "owner_group", "owner_user")
        serializer_class = ComponentSerializer

    class ComponentInstancesView(generics.ListAPIView):
        serializer_class = ComponentInstanceListSerializer

        def get_queryset(self):
            return ComponentInstance.objects.filter(
                component_id=self.kwargs["pk"]
            ).select_related("component", "location", "owner_group")

    class ComponentDesignsView(generics.ListAPIView):
        serializer_class = DesignListSerializer

        def get_queryset(self):
            design_ids = DesignElement.objects.filter(
                component_id=self.kwargs["pk"]
            ).values_list("design_id", flat=True).distinct()
            return Design.objects.filter(
                id__in=design_ids
            ).select_related("owner_group")

    # ── Component Inventory ───────────────────────────────────────────────────

    class ComponentInstanceListView(generics.ListAPIView):
        serializer_class = ComponentInstanceListSerializer
        filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
        search_fields    = ["tag", "serial_number", "component__name"]
        ordering_fields  = ["tag", "component__name", "created_on"]

        def get_queryset(self):
            qs = ComponentInstance.objects.select_related(
                "component", "location", "location__institution", "owner_group"
            ).all()
            for param, field in [
                ("component",   "component__name__icontains"),

                ("location",    "location__name__icontains"),
                ("owner_group", "owner_group__name__iexact"),
                ("institution", "location__institution__abbreviation__iexact"),
            ]:
                val = self.request.query_params.get(param)
                if val:
                    qs = qs.filter(**{field: val})
            return qs

    class ComponentInstanceDetailView(generics.RetrieveAPIView):
        queryset = ComponentInstance.objects.prefetch_related(
            "properties__property_type", "log_entries"
        ).select_related("component", "location", "location__institution",
                         "owner_group", "owner_user")
        serializer_class = ComponentInstanceSerializer
