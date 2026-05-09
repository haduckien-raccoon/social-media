from django.urls import path
from  apps.search.views import *

app_name = 'search'
urlpatterns = [
    path('', search_page_view, name='search_page'),
    path('api/search-history/', api_get_history, name='api_get_history'),
    path('api/save-history/', api_save_history, name='api_save_history'),
    path('api/search-users/', api_search_users, name='api_search_users'),
    path('api/search-hashtags/', api_search_hashtags, name='api_search_hashtags'),
]