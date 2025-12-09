from django.urls import path
from django.contrib import admin
from awards import views

urlpatterns = [
    # Админка
    path('admin/', admin.site.urls),

    # Главная страница
    path('', views.index, name='index'),

    # VK авторизация
    path('auth/login/', views.vk_login_page, name='login'),
    path('oauth/complete/vk-oauth2/', views.vk_oauth_complete, name='vk_oauth_complete'),
    path('auth/logout/', views.vk_logout, name='logout'),

    # Ссылки на этапы премии
    path('suggest-category/', views.suggest_category, name='suggest_category'),
    path('categories/', views.categories_list, name='categories_list'),
    path('suggest-nominee/<int:category_id>/', views.suggest_nominee, name='suggest_nominee'),
    path('vote/<int:category_id>/', views.vote, name='vote'),

    # Страница завершения этапа
    path('stage-finished/', views.stage_finished, name='stage_finished'),

    # Подсчёт результатов (только админ)
    path('count/', views.count, name='count'),

    # Публичные результаты
    path('results/', views.results_public, name='results_public'),

    # Генерация одноразовой ссылки для жюри
    path('generate-jury-token/', views.generate_jury_token, name='generate_jury_token'),
    path('generate-jury-token-ajax/', views.generate_jury_token_ajax, name='generate_jury_token_ajax'),

    # Авторизация жюри по одноразовому токену
    path('jury-login/<uuid:token>/', views.jury_login, name='jury_login'),
]
