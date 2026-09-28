# FROM python:3.12-alpine

# RUN apk update && apk add --no-cache \
#     postgresql-dev \
#     gcc \
#     g++ \
#     make \
#     cmake \
#     python3-dev \
#     musl-dev \
#     libmagic \
#     libjpeg-turbo-dev \
#     libpng-dev \
#     openblas-dev \
#     linux-headers

FROM python:3.12

RUN apt update && apt install -y \
    build-essential \
    libpq-dev \
    cmake \  
    libjpeg-dev \
    libpng-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libmagic-dev \
    libopenblas-dev

ENV PYTHONBUFFERED=1

WORKDIR /app

COPY requirements/development.txt requirements/development.txt

RUN pip install -r requirements/development.txt
# RUN pip install --no-cache-dir -r requirements/development.txt

COPY env_sample.txt .env

COPY . .

# CMD python3 manage.py runserver 0.0.0.0:5000
# CMD ["gunicorn", "--chdir", "/app", "master.wsgi:application", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2"]
EXPOSE 5000

# Gunicorn-managed uvicorn ASGI workers: keeps websockets, and recycles workers
# (--max-requests) so leaked DB connections/memory are reclaimed over time.
# The docker-compose `command:` mirrors this and is what runs in prod.
CMD ["gunicorn", "master.asgi:application", "-k", "uvicorn_worker.UvicornWorker", "-b", "0.0.0.0:5000", "--workers", "3", "--max-requests", "800", "--max-requests-jitter", "200", "--timeout", "120", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
# Old single-process server (no worker recycling):
# CMD ["daphne", "-b", "0.0.0.0", "-p", "5000", "master.asgi:application"]
# CMD ["python3", "manage.py", "runserver", "0.0.0.0:6000"]