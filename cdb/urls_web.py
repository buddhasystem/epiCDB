from django.urls import path
from django.contrib.auth import views as auth_views
from . import views_web

urlpatterns = [
    # Landing page: unauthenticated visitors are asked to log in here.
    # Already-authenticated visitors are bounced straight to the Dashboard.
    path("",                          auth_views.LoginView.as_view(
                                           template_name="cdb/login.html",
                                           redirect_authenticated_user=True,
                                       ),                                   name="login"),
    path("logout/",                   auth_views.LogoutView.as_view(),     name="logout"),

    path("dashboard/",                views_web.dashboard,        name="dashboard"),
    path("components/",               views_web.component_list,   name="component-list"),
    path("components/<str:pk>/",      views_web.component_detail, name="component-detail"),
    path("inventory/",                views_web.inventory_list,   name="inventory-list"),
    path("inventory/<str:pk>/",       views_web.inventory_detail, name="inventory-detail"),
    path("designs/",                  views_web.design_list,      name="design-list"),
    path("designs/<str:pk>/",         views_web.design_detail,    name="design-detail"),
    path("systems/",                  views_web.system_list,      name="system-list"),
    path("systems/<str:pk>/",         views_web.system_detail,    name="system-detail"),
    path("institutions/",             views_web.institution_list, name="institution-list"),
    path("logs/",                     views_web.log_list,         name="log-list"),
    path("users/",                    views_web.user_list,        name="user-list"),
    path("users/<str:username>/inventory/", views_web.user_inventory,  name="user-inventory"),
    path("locations/<str:pk>/inventory/",   views_web.location_inventory, name="location-inventory"),
]
