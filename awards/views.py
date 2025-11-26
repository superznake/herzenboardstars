from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required

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


# =========================
# Предложение номинаций
# =========================
@login_required
def suggest_category(request):
    award_config = AwardConfig.objects.first()
    if award_config and award_config.current_stage != 'suggest_cat':
        return render(request, "closed.html", {"message": "Этап предложения номинаций закрыт."})

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
@login_required
def categories_list(request):
    award_config = AwardConfig.objects.first()
    current_stage = award_config.current_stage if award_config else None
    categories = Category.objects.all()
    return render(request, "categories_list.html", {
        "categories": categories,
        "current_stage": current_stage
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

    return render(request, "suggest_nominee.html", {"form": form, "category": category})


# =========================
# Голосование пользователей
# =========================
@login_required
def vote(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    award_config = AwardConfig.objects.first()

    if award_config and award_config.current_stage != 'voting':
        return render(request, "closed.html", {"message": "Этап голосования закрыт."})

    nominees = Nominee.objects.filter(category=category)

    if request.method == 'POST':
        nominee_id = request.POST.get('nominee')
        if nominee_id:
            nominee = get_object_or_404(Nominee, id=nominee_id)

            # обновление существующего голоса
            existing_vote = Vote.objects.filter(user=request.user, nominee__category=category).first()
            if existing_vote:
                existing_vote.nominee = nominee
                existing_vote.jury = request.user.userprofile.is_jury
                existing_vote.save()
            else:
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
    token_obj = get_object_or_404(JuryToken, token=token)
    if not token_obj.is_valid():
        return render(request, "token_invalid.html")

    # Создаём пользователя, если ещё не существует
    if token_obj.user is None:
        user = User.objects.create(username=f"jury_{token_obj.token.hex[:8]}")
        user.set_unusable_password()
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.is_jury = True
        profile.save()

        token_obj.user = user
        token_obj.save()
    else:
        user = token_obj.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.is_jury = True
        profile.save()

    login(request, user)
    token_obj.used = True
    token_obj.save()
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
