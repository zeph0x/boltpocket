from django.urls import path
from . import views
from . import views_api
from . import views_boltcard
from . import views_lnurlp

urlpatterns = [
    path('', lambda r: __import__('django.http', fromlist=['HttpResponse']).HttpResponse(''), name='index'),
    path('wallet/', views.wallet_login, name='wallet-login'),
    path('wallet/auth/', views.wallet_auth, name='wallet-auth'),
    path('wallet/dashboard/', views.wallet_dashboard, name='wallet-dashboard'),

    # Wallet send + receive + settings + price
    path('wallet/send/', views.wallet_send, name='wallet-send'),
    path('wallet/receive/invoice/', views.wallet_receive_invoice, name='wallet-receive-invoice'),
    path('wallet/receive/charge-card/', views.wallet_charge_card, name='wallet-charge-card'),
    path('wallet/settings/', views.wallet_settings, name='wallet-settings'),
    path('wallet/price/', views.wallet_price, name='wallet-price'),

    # Recurring payments
    path('wallet/recurring/', views.wallet_recurring_list, name='wallet-recurring-list'),
    path('wallet/recurring/create/', views.wallet_recurring_create, name='wallet-recurring-create'),
    path('wallet/recurring/<int:rp_id>/history/', views.wallet_recurring_history, name='wallet-recurring-history'),
    path('wallet/recurring/<int:rp_id>/toggle/', views.wallet_recurring_toggle, name='wallet-recurring-toggle'),
    path('wallet/recurring/<int:rp_id>/delete/', views.wallet_recurring_delete, name='wallet-recurring-delete'),

    # Bolt Card
    path('wallet/boltcard/add/', views.wallet_add_card, name='wallet-add-card'),
    path('wallet/boltcard/<int:card_id>/', views.boltcard_detail, name='boltcard-detail'),

    # Bolt Card LNURL endpoints (public, called by POS)
    path('boltcard/scan/<str:external_id>/<str:card_secret>/', views_boltcard.lnurl_scan, name='boltcard-scan'),
    path('boltcard/callback/<int:hit_id>/', views_boltcard.lnurl_callback, name='boltcard-callback'),
    path('boltcard/auth/', views_boltcard.lnurl_auth, name='boltcard-auth'),

    # Device API (M5Stack, ESP32, etc.)
    path('api/v1/balance/', views_api.api_balance, name='api-balance'),

    # Lightning Address / LNURL-pay (LUD-16)
    path('.well-known/lnurlp/<str:address>/', views_lnurlp.lnurlp_metadata, name='lnurlp-metadata'),
    path('lnurlp/callback/<str:address>/', views_lnurlp.lnurlp_callback, name='lnurlp-callback'),
]
