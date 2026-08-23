from django.contrib import admin
from django.urls import include, path

from stock.views import landing_view

urlpatterns = [
    path('', landing_view, name='landing'),
    path('admin/', admin.site.urls),
    path('stock/', include('stock.urls')),
]