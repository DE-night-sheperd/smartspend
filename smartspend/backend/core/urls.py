from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import CategoryViewSet, MeView, ReceiptItemViewSet, ReceiptViewSet, RegisterView, StoreViewSet

router = DefaultRouter()
router.register('stores', StoreViewSet, basename='store')
router.register('categories', CategoryViewSet, basename='category')
router.register('receipts', ReceiptViewSet, basename='receipt')
router.register('receipt-items', ReceiptItemViewSet, basename='receiptitem')

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('', include(router.urls)),
]
