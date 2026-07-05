from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("", views.stock_list_view, name="stock_list"),
    path("register/", views.stock_register_view, name="stock_register"),
    path("edit/<int:pk>/", views.stock_edit_view, name="stock_edit"),
    path("stocktake/", views.stocktake_view, name="stocktake"),
    path("receive/", views.stock_receive_view, name="stock_receive"),
    path("ship/", views.stock_ship_view, name="stock_ship"),
    path("projection/", views.stock_projection_view, name="stock_projection"),
    path("master/", views.master_view, name="master"),
    path("api/products/<str:product_code>/", views.product_lookup_api, name="product_lookup_api"),
    path("inout/", views.inout_view, name="inout"),
    path("history/", views.history_view, name="history"),
    path("history/csv/", views.history_csv_view, name="history_csv"),
]
