from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
import medifind.views as medifind_views

urlpatterns = [
    path("admin/data-quality/", medifind_views.admin_data_quality_view, name="admin_data_quality_view"),
    path("admin/ai-model-performance/", medifind_views.admin_model_performance_view, name="admin_model_performance_view"),
    path("admin/", admin.site.urls),
    path("robots.txt", medifind_views.robots_txt, name="root_robots_txt"),
    path("sitemap.xml", medifind_views.sitemap_xml, name="root_sitemap_xml"),
    path("", include("medifind.urls")),
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.BASE_DIR / 'medifind/static'}),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

handler404 = 'medifind.views.custom_404_view'
handler500 = 'medifind.views.custom_500_view'
handler403 = 'medifind.views.custom_403_view'