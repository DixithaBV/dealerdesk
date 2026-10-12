from django.urls import path

from . import views

urlpatterns = [
    path("orders/", views.OrderListView.as_view()),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view()),
    *[path(f"orders/<str:order_number>/{a}/", views.OrderActionView.as_view(action=a))
      for a in ("confirm", "dispatch", "deliver", "cancel")],
]
