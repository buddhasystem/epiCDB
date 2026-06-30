from django.urls import path
from . import views_web

urlpatterns = [
    path("",                          views_web.dashboard,        name="dashboard"),
    path("components/",               views_web.component_list,   name="component-list"),
    path("components/<int:pk>/",      views_web.component_detail, name="component-detail"),
    path("inventory/",                views_web.inventory_list,   name="inventory-list"),
    path("inventory/<int:pk>/",       views_web.inventory_detail, name="inventory-detail"),
    path("designs/",                  views_web.design_list,      name="design-list"),
    path("designs/<int:pk>/",         views_web.design_detail,    name="design-detail"),
    path("systems/",                  views_web.system_list,      name="system-list"),
    path("systems/<int:pk>/",         views_web.system_detail,    name="system-detail"),
    path("institutions/",             views_web.institution_list, name="institution-list"),
    path("logs/",                     views_web.log_list,         name="log-list"),
]
