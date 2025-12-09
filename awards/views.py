import json
import logging
import uuid

import requests
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, get_backends, logout
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AwardConfig,
    SuggestedCategory,
    Category,
    SuggestedNominee,
    Nominee,
    Vote,
    JuryToken,
    FinalResult,
    UserProfile
)
from .forms import SuggestedCategoryForm, SuggestedNomineeForm


# =========================
# Главная страница
# =========================
def index(request):
    award_config = AwardConfig.objects.first()
    current_stage = award_config.current_stage if award_config else None

    # Основные категории
    main_categories = Category.objects.filter(is_main=True)

    return render(request, "index.html", {
        "award_config": award_config,
        "current_stage": current_stage,
        "main_categories": main_categories
    })


def vk_login_page(request):
    vk_auth_url = (
        "https://oauth.vk.com/authorize?"
        f"client_id={settings.VK_CLIENT_ID}"
        f"&display=page"
        f"&redirect_uri={settings.VK_REDIRECT_URI}"
        f"&scope=email"
        f"&response_type=code"
        f"&v=5.131"
    )
    return redirect(vk_auth_url)


@require_POST
def vk_logout(request):
    """Выход пользователя из системы"""
    logout(request)
    return redirect('index')


logger = logging.getLogger(__name__)


@csrf_exempt
def vk_oauth_complete(request):
    """Обработка редиректа с VK после OAuth через OneTap"""
    
    # Обработка GET запроса с кодом - показываем страницу для клиентского обмена
    if request.method == "GET":
        code = request.GET.get("code")
        if code:
            logger.info("VK Auth: GET redirect with code, showing client-side exchange page")
            return render(request, "registration/vk_exchange.html", {
                "code": code,
                "device_id": request.GET.get("device_id", ""),
                "csrf_token": request.META.get("CSRF_COOKIE", ""),
                "VK_APP_ID": settings.VK_CLIENT_ID,
                "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
            })
        else:
            logger.info("VK Auth: GET request to oauth endpoint, redirecting to login")
            return redirect("login")
    
    # Обработка POST запроса с user_id и user info (после клиентского обмена)
    if request.method != "POST":
        return render(request, "registration/login.html", {"error": "Неверный метод запроса."})
    
    user_id = request.POST.get("user_id")
    first_name = request.POST.get("first_name", "")
    last_name = request.POST.get("last_name", "")
    
    if not user_id:
        logger.error("VK Auth: Missing user_id in POST request")
        return render(request, "registration/login.html", {"error": "Не удалось получить данные пользователя от VK."})
    
    logger.info(f"VK Auth: Received user data for user_id: {user_id}")
    full_name = f"{first_name} {last_name}".strip() or "Пользователь VK"
    logger.info(f"VK Auth: User info: {full_name}")
    
    # Получаем или создаём пользователя
    try:
        user, created = User.objects.get_or_create(
            username=f"vk_{user_id}",
            defaults={
                "first_name": first_name,
                "last_name": last_name,
            }
        )
        
        # Если профиль отсутствует, создаём
        if not hasattr(user, "userprofile"):
            UserProfile.objects.create(user=user)
        
        # Логиним (указываем backend, так как у нас несколько backends)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        logger.info(f"VK Auth: User {user.username} logged in successfully")
        
        # Проверяем, есть ли в сессии токен жюри
        jury_token_str = request.session.get('jury_token')
        if jury_token_str:
            try:
                jury_token = uuid.UUID(jury_token_str)
                token_obj = JuryToken.objects.filter(token=jury_token, used=False).first()
                if token_obj and token_obj.is_valid():
                    # Привязываем токен к пользователю
                    token_obj.user = user
                    token_obj.save()
                    
                    # Устанавливаем статус жюри
                    user_profile, created = UserProfile.objects.get_or_create(
                        user=user,
                        defaults={'is_jury': True}
                    )
                    if not created:
                        user_profile.is_jury = True
                        user_profile.save()
                    
                    # Отмечаем токен как использованный
                    token_obj.used = True
                    token_obj.save()
                    
                    # Удаляем токен из сессии
                    del request.session['jury_token']
                    logger.info(f"VK Auth: Jury token {jury_token_str} associated with user {user.username}")
            except (ValueError, JuryToken.DoesNotExist) as e:
                logger.warning(f"VK Auth: Invalid jury token in session: {e}")
                # Удаляем невалидный токен из сессии
                if 'jury_token' in request.session:
                    del request.session['jury_token']
        
        return redirect("index")
        
    except Exception as e:
        logger.error(f"VK Auth: Error creating user: {str(e)}")
        return render(request, "registration/login.html", {"error": f"Ошибка при создании пользователя: {str(e)}"})


@csrf_exempt
def vkid_login(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid method"})

    data = json.loads(request.body)

    vk_user_id = data.get("user_id")
    token_payload = data.get("token_payload") or {}

    if not vk_user_id:
        return JsonResponse({"success": False, "error": "No user_id"})

    # Имя берём из токена
    first_name = token_payload.get("first_name", "")
    last_name = token_payload.get("last_name", "")

    # Создаём или получаем пользователя
    user, created = User.objects.get_or_create(
        username=f"vk_{vk_user_id}",
        defaults={"first_name": first_name}
    )

    if not hasattr(user, "userprofile"):
        UserProfile.objects.create(user=user)

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return JsonResponse({"success": True})


# =========================
# Предложение номинаций
# =========================
@login_required
def suggest_category(request):
    award_config = AwardConfig.objects.first()
    if award_config and award_config.current_stage != 'suggest_cat':
        return render(request, "closed.html", {"message": "Этап предложения номинаций закрыт."})

    # ---- Ограничение: не более 2 предложенных категорий ----
    user_suggestions_count = SuggestedCategory.objects.filter(user=request.user).count()
    if user_suggestions_count >= 2:
        return render(request, "closed.html", {
            "message": "Вы уже предложили максимальное количество номинаций (2)."
        })
    # ---------------------------------------------------------

    if request.method == 'POST':
        form = SuggestedCategoryForm(request.POST)
        if form.is_valid():
            suggested = form.save(commit=False)
            suggested.user = request.user
            suggested.save()
            return redirect('index')
    else:
        form = SuggestedCategoryForm()

    return render(request, "suggest_category.html", {"form": form, "award_config": award_config})


# =========================
# Список категорий
# =========================
def categories_list(request):
    award = AwardConfig.objects.first()

    main_categories = Category.objects.filter(is_main=True)
    extra_categories = Category.objects.filter(is_main=False)

    return render(request, "categories_list.html", {
        "main_categories": main_categories,
        "extra_categories": extra_categories,
        "current_stage": award.current_stage if award else None,
    })


# =========================
# Предложение номинантов
# =========================
@login_required
def suggest_nominee(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    award_config = AwardConfig.objects.first()

    if award_config and award_config.current_stage != 'suggest_nominee':
        return render(request, "closed.html", {"message": "Этап предложения номинантов закрыт."})

    # 🔥 Проверяем, предлагал ли этот пользователь номинанта в этой категории
    already = SuggestedNominee.objects.filter(
        category=category,
        user=request.user
    ).exists()

    if already:
        return render(request, "closed.html", {
            "message": "Вы уже предложили номинанта в этой категории."
        })

    if request.method == 'POST':
        form = SuggestedNomineeForm(request.POST)
        if form.is_valid():
            nominee = form.save(commit=False)
            nominee.category = category
            nominee.user = request.user
            nominee.save()
            return redirect('categories_list')
    else:
        form = SuggestedNomineeForm()

    return render(request, "suggest_nominee.html", {
        "form": form,
        "category": category
    })


# =========================
# Голосование пользователей
# =========================
@login_required
def vote(request, category_id):
    # Создаём профиль, если его нет
    if not hasattr(request.user, 'userprofile'):
        UserProfile.objects.create(user=request.user)

    category = get_object_or_404(Category, id=category_id)
    award_config = AwardConfig.objects.first()

    # Проверка текущего этапа
    if award_config and award_config.current_stage != 'voting':
        return render(request, "closed.html", {"message": "Этап голосования закрыт."})

    # Список номинантов для категории
    nominees = Nominee.objects.filter(category=category)

    if request.method == 'POST':
        nominee_id = request.POST.get('nominee')
        if nominee_id:
            nominee = get_object_or_404(Nominee, id=nominee_id)

            # Проверяем, есть ли уже голос пользователя в этой категории
            existing_vote = Vote.objects.filter(user=request.user, nominee__category=category).first()
            if existing_vote:
                # Обновляем существующий голос
                existing_vote.nominee = nominee
                existing_vote.jury = request.user.userprofile.is_jury
                existing_vote.save()
            else:
                # Создаём новый голос
                Vote.objects.create(
                    user=request.user,
                    nominee=nominee,
                    jury=request.user.userprofile.is_jury
                )

        return redirect('categories_list')

    return render(request, "vote.html", {"category": category, "nominees": nominees})


# =========================
# Подсчёт результатов — админ
# =========================
@staff_member_required
def count(request):
    award_config = AwardConfig.objects.first()
    categories = Category.objects.all()
    results_data = []

    jury_weight = 0.3
    user_weight = 0.7

    for category in categories:
        nominees = Nominee.objects.filter(category=category)
        category_results = []

        # Calculate total votes in this category for normalization
        total_jury_votes_in_category = Vote.objects.filter(
            nominee__category=category, 
            jury=True
        ).count()
        total_user_votes_in_category = Vote.objects.filter(
            nominee__category=category, 
            jury=False
        ).count()

        for nominee in nominees:
            jury_votes = nominee.vote_set.filter(jury=True).count()
            user_votes = nominee.vote_set.filter(jury=False).count()
            
            # Calculate weighted score:
            # - Jury votes contribute 30% of total weight (distributed proportionally)
            # - User votes contribute 70% of total weight (distributed proportionally)
            jury_contribution = 0.0
            user_contribution = 0.0
            
            if total_jury_votes_in_category > 0:
                # This nominee's share of jury votes * 30% weight
                jury_contribution = (jury_votes / total_jury_votes_in_category) * jury_weight
            
            if total_user_votes_in_category > 0:
                # This nominee's share of user votes * 70% weight
                user_contribution = (user_votes / total_user_votes_in_category) * user_weight
            
            total_score = jury_contribution + user_contribution

            category_results.append({
                'nominee': nominee,
                'jury_votes': jury_votes,
                'user_votes': user_votes,
                'total_score': total_score,
            })

        category_results.sort(key=lambda x: x['total_score'], reverse=True)
        results_data.append({'category': category, 'results': category_results})

    if request.method == 'POST':
        for cat_data in results_data:
            category = cat_data['category']
            for r in cat_data['results']:
                FinalResult.objects.update_or_create(
                    category=category,
                    nominee=r['nominee'],
                    defaults={
                        'jury_votes': r['jury_votes'],
                        'user_votes': r['user_votes'],
                        'total_score': r['total_score'],
                    }
                )
        return redirect('results_public')

    return render(request, "count.html", {"results_data": results_data, "award_config": award_config})


# =========================
# Авторизация жюри по токену
# =========================
def jury_login(request, token):
    """
    Авторизация жюри по одноразовому токену через VK.
    Пользователь должен войти через VK, после чего токен будет привязан к его аккаунту.
    """
    token_obj = get_object_or_404(JuryToken, token=token)

    # Проверка действительности токена
    if not token_obj.is_valid():
        return HttpResponse("Токен недействителен или уже использован.", status=400)

    # Если пользователь уже авторизован через VK, привязываем токен к нему
    if request.user.is_authenticated:
        # Проверяем, что пользователь авторизован через VK (username начинается с vk_)
        if request.user.username.startswith('vk_'):
            # Привязываем токен к пользователю
            token_obj.user = request.user
            token_obj.save()
            
            # Устанавливаем статус жюри
            user_profile, created = UserProfile.objects.get_or_create(
                user=request.user,
                defaults={'is_jury': True}
            )
            if not created:
                user_profile.is_jury = True
                user_profile.save()
            
            # Отмечаем токен как использованный
            token_obj.used = True
            token_obj.save()
            
            return redirect('index')
        else:
            # Пользователь авторизован, но не через VK - выходим и просим войти через VK
            logout(request)
    
    # Пользователь не авторизован - сохраняем токен в сессии и перенаправляем на VK логин
    request.session['jury_token'] = str(token)
    return redirect('login')


# =========================
# Этап завершён
# =========================
@login_required
def stage_finished(request):
    return render(request, "finished.html")


# =========================
# Публичные результаты
# =========================
def results_public(request):
    results_data = []
    categories = Category.objects.all()
    for category in categories:
        winner = FinalResult.objects.filter(category=category).order_by('-total_score').first()
        if winner:
            results_data.append({'category': category, 'winner': winner.nominee})
    return render(request, "results_public.html", {"results_data": results_data})


# =========================
# Генерация токена жюри
# =========================
@staff_member_required
def generate_jury_token(request):
    link = None
    if request.method == "POST":
        token_obj = JuryToken.objects.create()
        link = request.build_absolute_uri(f"/jury-login/{token_obj.token}/")
    return render(request, "generate_token.html", {"link": link})


@staff_member_required
@csrf_exempt
def generate_jury_token_ajax(request):
    if request.method == "POST":
        token_obj = JuryToken.objects.create()
        link = request.build_absolute_uri(f"/jury-login/{token_obj.token}/")
        return JsonResponse({"link": link})
    return JsonResponse({"error": "Invalid method"}, status=400)
