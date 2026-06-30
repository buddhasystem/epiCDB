from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("",       include("cdb.urls_web")),   # web UI (server-rendered)
]

# REST API routes — only registered when djangorestframework is installed.
try:
    import rest_framework  # noqa
    from cdb import views
    urlpatterns += [
        path("api/",                                     views.api_root,                        name="api-root"),
        path("api/groups/",                              views.GroupListView.as_view(),          name="group-list"),
        path("api/groups/<int:pk>/",                     views.GroupDetailView.as_view(),        name="group-detail"),
        path("api/institutions/",                        views.InstitutionListView.as_view(),    name="institution-list"),
        path("api/locations/",                           views.LocationListView.as_view(),       name="location-list"),
        path("api/locations/<int:pk>/",                  views.LocationDetailView.as_view(),     name="location-detail"),
        path("api/locations/<int:pk>/children/",         views.LocationChildrenView.as_view(),   name="location-children"),
        path("api/locations/<int:pk>/instances/",        views.LocationInstancesView.as_view(),  name="location-instances"),
        path("api/components/",                          views.ComponentListView.as_view(),      name="component-list-api"),
        path("api/components/<int:pk>/",                 views.ComponentDetailView.as_view(),    name="component-detail-api"),
        path("api/components/<int:pk>/instances/",       views.ComponentInstancesView.as_view(), name="component-instances"),
        path("api/components/<int:pk>/designs/",         views.ComponentDesignsView.as_view(),   name="component-designs"),
        path("api/inventory/",                           views.ComponentInstanceListView.as_view(),   name="instance-list"),
        path("api/inventory/<int:pk>/",                  views.ComponentInstanceDetailView.as_view(), name="instance-detail"),
        path("api/inventory/qr/<str:qr_id>/",            views.ComponentInstanceByQRView.as_view(),   name="instance-by-qr"),
        path("api/designs/",                             views.DesignListView.as_view(),   name="design-list-api"),
        path("api/designs/<int:pk>/",                    views.DesignDetailView.as_view(), name="design-detail-api"),
        path("api/designs/<int:pk>/bom/",                views.DesignBOMView.as_view(),    name="design-bom"),
        path("api/property-types/",                      views.PropertyTypeListView.as_view(), name="propertytype-list"),
        path("api/logs/",                                views.LogListView.as_view(),          name="log-list-api"),
    ]
except ImportError:
    pass
