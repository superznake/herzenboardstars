import os
import django
from django.contrib.auth import get_user_model

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django.setup()

User = get_user_model()

username = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "admin123")

if not User.objects.filter(username=username).exists():
    print(f"Создаём суперюзера {username}")
    User.objects.create_superuser(username=username, password=password)
else:
    print(f"Суперюзер {username} уже существует")
