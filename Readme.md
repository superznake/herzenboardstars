docker build -t herzenstars .
docker run -p 8008:8000 --env-file .env -v ~/herzenstars_data/db:/app/db -v ~/herzenstars_data/static:/app/static herzenstars
