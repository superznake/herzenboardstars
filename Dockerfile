FROM python:3.12-slim

WORKDIR /app

COPY req.txt .
RUN pip install --no-cache-dir -r req.txt gunicorn python-dotenv

COPY . .

EXPOSE 8000

# При старте контейнера подгружаем .env и запускаем Django
CMD python manage.py migrate --noinput && \
    python manage.py collectstatic --noinput && \
    python create_superuser.py && \
    gunicorn project.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
