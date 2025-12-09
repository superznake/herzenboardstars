import json
import logging

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

logger = logging.getLogger(__name__)

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
    """Render login page with VK ID SDK"""
    return render(request, "registration/login.html", {
        "VK_APP_ID": settings.VK_CLIENT_ID,
        "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
    })


@require_POST
def vk_logout(request):
    """Выход пользователя из системы"""
    logout(request)
    return redirect('index')


@csrf_exempt  # CSRF проверка через токен, но можно временно отключить для теста
def vk_oauth_complete(request):
    """Обработка редиректа с VK после OAuth через OneTap"""

    if request.method != "POST":
        return render(request, "registration/login.html", {
            "error": "Неверный метод запроса.",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    code = request.POST.get("code")
    if not code:
        logger.warning("VK OAuth: No code received in request")
        return render(request, "registration/login.html", {
            "error": "Не удалось получить код от VK.",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    # Проверяем наличие необходимых настроек
    if not settings.VK_CLIENT_ID or not settings.VK_APP_SECRET or not settings.VK_REDIRECT_URI:
        logger.error("VK OAuth: Missing VK configuration (VK_CLIENT_ID, VK_APP_SECRET, or VK_REDIRECT_URI)")
        return render(request, "registration/login.html", {
            "error": "Ошибка конфигурации сервера. Обратитесь к администратору.",
            "VK_APP_ID": settings.VK_CLIENT_ID or "",
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI or "",
        })

    # Обмен кода на access_token
    token_url = "https://oauth.vk.com/access_token"
    params = {
        "client_id": settings.VK_CLIENT_ID,
        "client_secret": settings.VK_APP_SECRET,
        "redirect_uri": settings.VK_REDIRECT_URI,
        "code": code,
    }
    
    try:
        logger.info(f"VK OAuth: Exchanging code for token (client_id: {settings.VK_CLIENT_ID})")
        resp = requests.get(token_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        logger.debug(f"VK OAuth: Token response received")
    except requests.RequestException as e:
        logger.error(f"VK OAuth: Request exception: {str(e)}")
        return render(request, "registration/login.html", {
            "error": f"Ошибка при запросе к VK: {str(e)}",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    if "error" in data:
        error_msg = data.get("error_description", data.get("error", "Ошибка авторизации VK."))
        logger.warning(f"VK OAuth: Error from VK API: {error_msg}")
        return render(request, "registration/login.html", {
            "error": error_msg,
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    # VK access_token response содержит: access_token, expires_in, user_id
    # НЕ содержит first_name и last_name - нужно сделать отдельный запрос
    access_token = data.get("access_token")
    vk_user_id = data.get("user_id")
    
    if not access_token or not vk_user_id:
        return render(request, "registration/login.html", {
            "error": "Не удалось получить токен доступа от VK.",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    # Получаем информацию о пользователе из VK API
    first_name = ""
    last_name = ""
    try:
        api_url = "https://api.vk.com/method/users.get"
        api_params = {
            "user_ids": vk_user_id,
            "fields": "first_name,last_name",
            "access_token": access_token,
            "v": "5.131",
        }
        logger.debug(f"VK OAuth: Fetching user info for user_id: {vk_user_id}")
        api_resp = requests.get(api_url, params=api_params, timeout=10)
        api_resp.raise_for_status()
        api_data = api_resp.json()
        
        if "error" in api_data:
            logger.warning(f"VK OAuth: Error fetching user info: {api_data.get('error')}")
        else:
            users = api_data.get("response", [])
            if users and len(users) > 0:
                user_data = users[0]
                first_name = user_data.get("first_name", "")
                last_name = user_data.get("last_name", "")
                logger.info(f"VK OAuth: User info retrieved: {first_name} {last_name}")
    except requests.RequestException as e:
        logger.warning(f"VK OAuth: Could not fetch user info: {str(e)}, continuing without it")

    # Получаем или создаём пользователя
    try:
        user, created = User.objects.get_or_create(
            username=f"vk_{vk_user_id}",
            defaults={"first_name": first_name, "last_name": last_name},
        )
        
        # Обновляем имя, если пользователь уже существовал
        if not created and (first_name or last_name):
            if first_name:
                user.first_name = first_name
            if last_name:
                user.last_name = last_name
            user.save()

        # Если профиль отсутствует, создаём
        if not hasattr(user, "userprofile"):
            UserProfile.objects.create(user=user)

        # Логиним
        login(request, user)
        logger.info(f"VK OAuth: User {user.username} logged in successfully")
        return redirect("index")
    except Exception as e:
        logger.error(f"VK OAuth: Error creating/logging in user: {str(e)}")
        return render(request, "registration/login.html", {
            "error": "Ошибка при создании пользователя. Попробуйте еще раз.",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })


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

    login(request, user)

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

        for nominee in nominees:
            jury_votes = nominee.vote_set.filter(jury=True).count()
            user_votes = nominee.vote_set.filter(jury=False).count()
            total_score = jury_votes * jury_weight + user_votes * user_weight

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
    """
    token_obj = get_object_or_404(JuryToken, token=token)

    # Проверка действительности токена
    if not token_obj.is_valid():
        return HttpResponse("Токен недействителен или уже использован.", status=400)

    # Если пользователь ещё не привязан к токену, создаём временного VK-пользователя
    if token_obj.user is None:
        username = f"jury_{token_obj.token.hex[:8]}"
        user = User.objects.create(username=username)
        user.set_unusable_password()
        user.save()
        # профиль с is_jury=True
        UserProfile.objects.create(user=user, is_jury=True)
        token_obj.user = user
        token_obj.save()
    else:
        user = token_obj.user
        # Обновляем статус жюри на всякий случай
        user_profile = getattr(user, 'userprofile', None)
        if user_profile:
            user_profile.is_jury = True
            user_profile.save()
        else:
            UserProfile.objects.create(user=user, is_jury=True)

    # Логиним пользователя
    login(request, user)

    # Отмечаем токен как использованный
    token_obj.used = True
    token_obj.save()

    # Редирект на текущий этап премии
    return redirect('index')


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
