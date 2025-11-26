from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),

    # Категории и предложения
    path('categories/', views.categories_list, name='categories_list'),
    path('suggest-category/', views.suggest_category, name='suggest_category'),
    path('suggest-nominee/<int:category_id>/', views.suggest_nominee, name='suggest_nominee'),

    # Голосование
    path('vote/<int:category_id>/', views.vote, name='vote'),

    # Этап завершён
    path('finished/', views.stage_finished, name='stage_finished'),

    # Результаты
    path('results/', views.results_public, name='results_public'),
    path('count/', views.count, name='count'),

    # Генерация токенов жюри
    path('generate-jury-token/', views.generate_jury_token, name='generate_jury_token'),
    path('generate-jury-token-ajax/', views.generate_jury_token_ajax, name='generate_jury_token_ajax'),

    # Авторизация жюри по токену
    path('oauth/', include('social_django.urls', namespace='social')),
    path('jury-login/<uuid:token>/', views.jury_login, name='jury_login'),
]
