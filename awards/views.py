import logging

import requests
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST

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
    """Страница входа через VK ID"""
    return render(request, "registration/login.html", {
        "VK_APP_ID": settings.VK_CLIENT_ID,
        "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
    })


@require_POST
def vk_logout(request):
    """Выход пользователя"""
    logout(request)
    return redirect('index')


@csrf_exempt
def vk_oauth_complete(request):
    """Обработка авторизации через VK ID SDK"""
    
    # VK ID SDK может отправлять код через GET (редирект) или POST (форма)
    if request.method == "GET":
        code = request.GET.get("code")
        device_id = request.GET.get("device_id")
        if not code:
            logger.info("VK Auth: GET request without code, redirecting to login")
            return redirect('login')
        logger.info("VK Auth: Received code via GET redirect")
    elif request.method == "POST":
        code = request.POST.get("code")
        device_id = request.POST.get("device_id")
        logger.info("VK Auth: Received code via POST")
    else:
        logger.warning(f"VK Auth: Invalid method {request.method}")
        return redirect('login')
    
    if not code:
        logger.warning("VK Auth: No code received")
        return render(request, "registration/login.html", {
            "error": "Не удалось получить код от VK.",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    if not settings.VK_CLIENT_ID or not settings.VK_APP_SECRET:
        logger.error("VK Auth: Missing configuration")
        return render(request, "registration/login.html", {
            "error": "Ошибка конфигурации сервера.",
            "VK_APP_ID": settings.VK_CLIENT_ID or "",
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI or "",
        })

    # Обмениваем код на токен через VK ID API
    token_url = "https://id.vk.com/v1/oauth/token"
    token_data = {
        "client_id": str(settings.VK_CLIENT_ID),
        "client_secret": settings.VK_APP_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }
    if device_id:
        token_data["device_id"] = device_id
    
    try:
        logger.info(f"VK Auth: Exchanging code for token")
        resp = requests.post(token_url, json=token_data, timeout=10)
        logger.debug(f"VK Auth: Response {resp.status_code}: {resp.text}")
        
        if resp.status_code != 200:
            error_data = resp.json() if resp.text else {}
            error_msg = error_data.get("error_description", error_data.get("error", "Ошибка обмена кода"))
            logger.error(f"VK Auth: Token exchange failed: {error_msg}")
            return render(request, "registration/login.html", {
                "error": f"Ошибка авторизации: {error_msg}",
                "VK_APP_ID": settings.VK_CLIENT_ID,
                "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
            })
        
        token_response = resp.json()
        
        if "error" in token_response:
            error_msg = token_response.get("error_description", token_response.get("error", "Ошибка авторизации"))
            logger.error(f"VK Auth: API error: {error_msg}")
            return render(request, "registration/login.html", {
                "error": error_msg,
                "VK_APP_ID": settings.VK_CLIENT_ID,
                "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
            })
        
        access_token = token_response.get("access_token")
        vk_user_id = token_response.get("user_id")
        
        if not access_token or not vk_user_id:
            logger.error(f"VK Auth: Missing token or user_id in response: {token_response}")
            return render(request, "registration/login.html", {
                "error": "Не удалось получить данные от VK.",
                "VK_APP_ID": settings.VK_CLIENT_ID,
                "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
            })
        
    except requests.RequestException as e:
        logger.error(f"VK Auth: Request failed: {str(e)}")
        return render(request, "registration/login.html", {
            "error": f"Ошибка соединения с VK: {str(e)}",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })

    # Получаем информацию о пользователе
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
        api_resp = requests.get(api_url, params=api_params, timeout=10)
        if api_resp.status_code == 200:
            api_data = api_resp.json()
            if "response" in api_data and api_data["response"]:
                user_data = api_data["response"][0]
                first_name = user_data.get("first_name", "")
                last_name = user_data.get("last_name", "")
                logger.info(f"VK Auth: User info: {first_name} {last_name}")
    except Exception as e:
        logger.warning(f"VK Auth: Could not fetch user info: {str(e)}")

    # Создаём или получаем пользователя
    try:
        user, created = User.objects.get_or_create(
            username=f"vk_{vk_user_id}",
            defaults={"first_name": first_name, "last_name": last_name},
        )
        
        if not created and (first_name or last_name):
            if first_name:
                user.first_name = first_name
            if last_name:
                user.last_name = last_name
            user.save()

        if not hasattr(user, "userprofile"):
            UserProfile.objects.create(user=user)

        login(request, user)
        logger.info(f"VK Auth: User {user.username} logged in")
        return redirect("index")
        
    except Exception as e:
        logger.error(f"VK Auth: Error creating user: {str(e)}")
        return render(request, "registration/login.html", {
            "error": "Ошибка при создании пользователя.",
            "VK_APP_ID": settings.VK_CLIENT_ID,
            "VK_REDIRECT_URI": settings.VK_REDIRECT_URI,
        })


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

    # Проверяем, предлагал ли этот пользователь номинанта в этой категории
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
