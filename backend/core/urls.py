from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    AppleSignInView,
    AuthConfigView,
    CategoryViewSet,
    GeminiKeyConnectView,
    GeminiKeyDisconnectView,
    GeminiKeyStatusView,
    LoyaltyPointsViewSet,
    MeView,
    ReceiptItemViewSet,
    ReceiptViewSet,
    RegisterView,
    RequestLoginCodeView,
    RequestSmsCodeView,
    RequestWhatsappCodeView,
    StoreViewSet,
    VerifyLoginCodeView,
    VerifySmsCodeView,
    VerifyWhatsappCodeView,
)

router = DefaultRouter()
router.register('stores', StoreViewSet, basename='store')
router.register('categories', CategoryViewSet, basename='category')
router.register('receipts', ReceiptViewSet, basename='receipt')
router.register('receipt-items', ReceiptItemViewSet, basename='receiptitem')
router.register('points', LoyaltyPointsViewSet, basename='loyaltypoints')

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/login-code/', RequestLoginCodeView.as_view(), name='request_login_code'),
    path('auth/verify-login-code/', VerifyLoginCodeView.as_view(), name='verify_login_code'),
    path('auth/login-code/sms/', RequestSmsCodeView.as_view(), name='request_login_code_sms'),
    path('auth/verify-login-code/sms/', VerifySmsCodeView.as_view(), name='verify_login_code_sms'),
    path('auth/login-code/whatsapp/', RequestWhatsappCodeView.as_view(), name='request_login_code_whatsapp'),
    path('auth/verify-login-code/whatsapp/', VerifyWhatsappCodeView.as_view(), name='verify_login_code_whatsapp'),
    path('auth/apple/', AppleSignInView.as_view(), name='apple_sign_in'),
    path('auth/config/', AuthConfigView.as_view(), name='auth_config'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('me/gemini-key/', GeminiKeyStatusView.as_view(), name='gemini_key_status'),
    path('me/gemini-key/connect/', GeminiKeyConnectView.as_view(), name='gemini_key_connect'),
    path('me/gemini-key/disconnect/', GeminiKeyDisconnectView.as_view(), name='gemini_key_disconnect'),
    path('', include(router.urls)),
]
