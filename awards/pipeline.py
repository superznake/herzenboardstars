from .models import UserProfile


def save_jury_status(backend, user, response, *args, **kwargs):
    """
    Если пользователь уже зарегистрирован как жюри через одноразовую ссылку,
    сохраняем статус при последующих входах через VK.
    """
    # Убедимся, что профиль существует
    profile, created = UserProfile.objects.get_or_create(user=user)

    # Если уже был жюри, ничего не меняем
    if profile.is_jury:
        return

    # Иначе обычный пользователь — профиль уже создан
    # можно добавить логику для назначения жюри по другим критериям
    # profile.is_jury = False # по умолчанию
    profile.save()
