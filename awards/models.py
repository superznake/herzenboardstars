import uuid
from datetime import timedelta

from django.utils import timezone
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# =========================
# Профиль пользователя — для жюри
# =========================
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_jury = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} ({'Жюри' if self.is_jury else 'Участник'})"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.userprofile.save()


# =========================
# Конфигурация премии и текущий этап
# =========================
class AwardConfig(models.Model):
    name = models.CharField(max_length=200, default="Онлайн-премия")
    description = models.TextField(blank=True)

    STAGE_CHOICES = [
        ('suggest_cat', 'Предложение номинаций'),
        ('finished', 'Этап проверки админами'),
        ('suggest_nominee', 'Предложение номинантов'),
        ('voting', 'Голосование'),
        ('results', 'Публикация результатов после награждения'),
    ]
    current_stage = models.CharField(max_length=30, choices=STAGE_CHOICES, default='suggest_cat')

    def __str__(self):
        return f"{self.name} ({self.get_current_stage_display()})"

    def get_current_stage_display(self):
        return dict(self.STAGE_CHOICES).get(self.current_stage, 'Неизвестно')


# =========================
# Категории премии
# =========================
class Category(models.Model):
    name = models.CharField("Название категории", max_length=200)
    description = models.TextField("Описание", blank=True)
    is_main = models.BooleanField(default=True)  # True = основная, False = дополнительная

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"


# =========================
# Предложенные категории пользователями
# =========================
class SuggestedCategory(models.Model):
    name = models.CharField("Название номинации", max_length=200)
    description = models.TextField("Описание", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    approved = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Предложенная номинация"
        verbose_name_plural = "Предложенные номинации"


# =========================
# Номинанты в категориях
# =========================
class Nominee(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField("Имя номинанта", max_length=200)
    description = models.TextField("Описание", blank=True)

    def __str__(self):
        return f"{self.name} ({self.category.name})"

    class Meta:
        verbose_name = "Номинант"
        verbose_name_plural = "Номинанты"


# =========================
# Предложенные номинанты пользователями
# =========================
class SuggestedNominee(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField("Имя номинанта", max_length=200)
    description = models.TextField("Описание", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    approved = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.category.name})"

    class Meta:
        verbose_name = "Предложенный номинант"
        verbose_name_plural = "Предложенные номинанты"


# =========================
# Голоса
# =========================
class Vote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    nominee = models.ForeignKey(Nominee, on_delete=models.CASCADE)
    jury = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Голос: {self.user.username} → {self.nominee.name} ({'Жюри' if self.jury else 'Пользователь'})"

    class Meta:
        verbose_name = "Голос"
        verbose_name_plural = "Голоса"
        unique_together = ('user', 'nominee')


# =========================
# Итоговые результаты
# =========================
class FinalResult(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    nominee = models.ForeignKey(Nominee, on_delete=models.CASCADE)
    jury_votes = models.PositiveIntegerField(default=0)
    user_votes = models.PositiveIntegerField(default=0)
    total_score = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('category', 'nominee')


# =========================
# Одноразовые токены для жюри
# =========================
def default_expire():
    return timezone.now() + timedelta(days=1)


class JuryToken(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True)
    expires_at = models.DateTimeField(default=default_expire)

    def is_valid(self):
        return not self.used and self.expires_at > timezone.now()
