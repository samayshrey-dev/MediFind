from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("medicine/", views.medicine_detail, name="medicine"),
    path("pharmacy/", views.pharmacy_detail, name="pharmacy"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
    "medicines/",
    views.medicines,
    name="medicines"
),

path(
    "medicines/add/",
    views.add_medicine,
    name="add_medicine"
),

path(
    "medicines/edit/<int:pk>/",
    views.edit_medicine,
    name="edit_medicine"
),

path(
    "medicines/delete/<int:pk>/",
    views.delete_medicine,
    name="delete_medicine"
),

path(
    "pharmacies/",
    views.pharmacies,
    name="pharmacies"
),

path(
    "pharmacies/add/",
    views.add_pharmacy,
    name="add_pharmacy"
),

path(
    "pharmacies/edit/<int:pk>/",
    views.edit_pharmacy,
    name="edit_pharmacy"
),

path(
    "pharmacies/delete/<int:pk>/",
    views.delete_pharmacy,
    name="delete_pharmacy"
),
path(
    "inventory/",
    views.inventory,
    name="inventory"
),

path(
    "inventory/add/",
    views.add_inventory,
    name="add_inventory"
),

path(
    "inventory/edit/<int:pk>/",
    views.edit_inventory,
    name="edit_inventory"
),

path(
    "inventory/delete/<int:pk>/",
    views.delete_inventory,
    name="delete_inventory"
),
path(
    "login/",
    auth_views.LoginView.as_view(
        template_name="login.html"
    ),
    name="login",
),

path(
    "logout/",
    auth_views.LogoutView.as_view(),
    name="logout",
),

path(
    "register/",
    views.register,
    name="register",
),
path(
    "dashboard-redirect/",
    views.dashboard_redirect,
    name="dashboard_redirect",
),
]