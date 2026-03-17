from django.contrib import admin
from django.urls import include, path
from accounts.views_admin import node_stats, accounting, generate_wallets

urlpatterns = [
    path('admin/node-stats/', node_stats, name='admin-node-stats'),
    path('admin/accounting/', accounting, name='admin-accounting'),
    path('admin/generate-wallets/', generate_wallets, name='admin-generate-wallets'),
    path('admin/', admin.site.urls),
    path('', include('wallets.urls')),
]
