from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("api/pharmacies/nearby/", views.nearby_pharmacies_api, name="nearby_pharmacies_api"),
    path("api/ai/search/", views.ai_search_api, name="ai_search_api"),
    path("api/ai/interpret/", views.ai_commerce_agent_interpret, name="ai_commerce_agent_interpret"),
    path("api/ai/agent/search/", views.ai_commerce_agent_search, name="ai_commerce_agent_search"),
    path("api/ai/agent/approve/", views.ai_commerce_agent_approve, name="ai_commerce_agent_approve"),
    path("api/ai/agent/audit/<str:session_id>/", views.ai_commerce_agent_audit, name="ai_commerce_agent_audit"),
    path("api/commerce/snapshot/", views.commerce_create_snapshot, name="commerce_create_snapshot"),
    path("api/payments/create-order/", views.commerce_create_razorpay_order, name="commerce_create_razorpay_order"),
    path("api/payments/pay-reservation/<int:reservation_id>/", views.commerce_pay_reservation, name="commerce_pay_reservation"),
    path("api/payments/verify/", views.commerce_verify_payment, name="commerce_verify_payment"),
    path("api/payments/fail/", views.commerce_fail_payment, name="commerce_fail_payment"),
    path("api/payments/razorpay/webhook/", views.commerce_razorpay_webhook, name="commerce_razorpay_webhook"),
    path("api/orders/<str:order_reference>/", views.commerce_order_status, name="commerce_order_status"),
    path("orders/confirmed/<str:order_reference>/", views.order_confirmed_view, name="order_confirmed_view"),
    path("api/notifications/stock-alert/", views.subscribe_stock_alert, name="subscribe_stock_alert"),

    # Medicine Intelligence (AI #3) & Admin Quality Endpoints
    path("api/ai/medicine/understand/", views.medicine_understand_api, name="medicine_understand_api"),
    path("api/ai/medicine/suggest/", views.medicine_suggest_api, name="medicine_suggest_api"),
    path("admin/data-quality/", views.admin_data_quality_view, name="admin_data_quality_view"),

    # Predictive Inventory & Demand Intelligence (AI #4) Endpoints
    path("api/pharmacy/ai/inventory-insights/", views.pharmacy_inventory_insights_api, name="pharmacy_inventory_insights_api"),
    path("api/pharmacy/ai/demand-forecast/<int:medicine_id>/", views.pharmacy_demand_forecast_api, name="pharmacy_demand_forecast_api"),
    path("pharmacy/inventory-intelligence/", views.pharmacy_inventory_intelligence_view, name="pharmacy_inventory_intelligence_view"),
    path("api/pharmacy/ai/retrain/", views.retrain_forecasting_model_api, name="retrain_forecasting_model_api"),
    path("admin/ai-model-performance/", views.admin_model_performance_view, name="admin_model_performance_view"),

    # Pharmacy Analytics & Business Intelligence (AI #5) Endpoints
    path("pharmacy/analytics/", views.pharmacy_analytics_bi_view, name="pharmacy_analytics_bi_view"),
    path("api/pharmacy/analytics/overview/", views.pharmacy_analytics_overview_api, name="pharmacy_analytics_overview_api"),
    path("api/pharmacy/analytics/trends/", views.pharmacy_analytics_trends_api, name="pharmacy_analytics_trends_api"),
    path("api/pharmacy/analytics/medicines/", views.pharmacy_analytics_medicines_api, name="pharmacy_analytics_medicines_api"),
    path("api/pharmacy/analytics/insights/", views.pharmacy_analytics_insights_api, name="pharmacy_analytics_insights_api"),
    path("api/pharmacy/analytics/anomalies/", views.pharmacy_analytics_anomalies_api, name="pharmacy_analytics_anomalies_api"),
    path("api/pharmacy/analytics/ask/", views.pharmacy_analytics_ask_api, name="pharmacy_analytics_ask_api"),
    path("admin/pharmacy-benchmarking/", views.admin_pharmacy_benchmarking_view, name="admin_pharmacy_benchmarking_view"),

    # Multilingual & Voice Search (AI #6) Endpoints
    path("api/ai/multilingual/search/", views.ai_multilingual_search_api, name="ai_multilingual_search_api"),
    path("admin/multilingual-analytics/", views.admin_multilingual_analytics_view, name="admin_multilingual_analytics_view"),





    path(
        "medicine/<int:id>/",
        views.medicine_detail,
        name="medicine_detail"
    ),

    path(
        "pharmacy/<int:id>/",
        views.pharmacy_detail,
        name="pharmacy_detail"
    ),
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
    "inventory/template/download/",
    views.download_inventory_template,
    name="download_inventory_template"
),
path(
    "inventory/upload/",
    views.upload_inventory_excel,
    name="upload_inventory_excel"
),
path(
    "inventory/export/",
    views.export_inventory_excel,
    name="export_inventory_excel"
),
path(
    "pharmacy/api-settings/",
    views.pharmacy_api_settings,
    name="pharmacy_api_settings"
),
path(
    "api/pharmacy-system/mock-inventory/",
    views.mock_pharmacy_system_api,
    name="mock_pharmacy_system_api"
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
    name="delete_inventory",
),

path(
    "inventory/<int:pk>/update-stock/",
    views.update_stock,
    name="update_stock",
),

path(
    "inventory/<int:pk>/history/",
    views.inventory_history,
    name="inventory_history",
),
    path(
        "login/",
        LoginView.as_view(
            template_name="login.html",
            redirect_authenticated_user=True
        ),
        name="login"
    ),

    path(
        "logout/",
        LogoutView.as_view(),
        name="logout"
    ),

    path(
        "password-reset/",
        views.forgot_password_request,
        name="password_reset"
    ),
    path(
        "password-reset/verify/",
        views.forgot_password_verify,
        name="password_reset_verify"
    ),
    path(
        "api/auth/resend-otp/",
        views.forgot_password_resend_api,
        name="password_reset_resend_otp"
    ),

    path(
        "register/",
        views.register,
        name="register"
    ),

    path(
        "profile/",
        views.profile,
        name="profile"
    ),
path(
    "dashboard-redirect/",
    views.dashboard_redirect,
    name="dashboard_redirect"
),
path(
    "reserve/<int:inventory_id>/",
    views.reserve_medicine,
    name="reserve_medicine"
),

path(
    "reservations/",
    views.reservations,
    name="reservations"
),

path(
    "reservations/<int:id>/accept/",
    views.accept_reservation,
    name="accept_reservation"
),

path(
    "reservations/<int:id>/complete/",
    views.complete_reservation,
    name="complete_reservation"
),

path(
    "reservations/<int:id>/reject/",
    views.reject_reservation,
    name="reject_reservation"
),

path(
    "my-reservations/",
    views.my_reservations,
    name="my_reservations"
),

path(
    "search-history/",
    views.search_history,
    name="search_history"
),
path(
    "pharmacy-dashboard/",
    views.pharmacy_dashboard,
    name="pharmacy_dashboard"
),
path(
    "search/suggestions/",
    views.search_suggestions,
    name="search_suggestions"
),
path(
    "notifications/",
    views.notifications_api,
    name="notifications_api"
),
path(
    "reservation-history/",
    views.reservation_history,
    name="reservation_history"
),
path(
    "toggle-pharmacy-status/",
    views.toggle_pharmacy_status,
    name="toggle_pharmacy_status"
),
path("privacy/", views.privacy_policy, name="privacy"),
path("terms/", views.terms_of_service, name="terms"),
path("thank-you/", views.thank_you_view, name="thank_you"),
path("robots.txt", views.robots_txt, name="robots_txt"),
path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
path("404/", views.custom_404_view, name="custom_404_preview"),
]

