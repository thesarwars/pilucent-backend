# Pilucent backend image, used by docker-compose.yml (local development) and
# docker-compose.prod.yml (production). Configuration comes from the environment
# at run time -- no .env is baked into the image.

FROM python:3.12-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build: compilers and libpq for the packages without wheels (psycopg2, ...).
# Runtime: Pango and HarfBuzz for WeasyPrint (invoice/report PDFs), libGL and
# GLib for OpenCV (bank-statement PDF extraction, imported at URLconf load),
# libmagic, image codecs, and Bangla fonts so Bangla text renders in PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libpq-dev \
        libjpeg-dev \
        libpng-dev \
        libopenblas-dev \
        libmagic1 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libffi-dev \
        libgl1 \
        libglib2.0-0 \
        fonts-dejavu-core \
        fonts-beng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements/development.txt requirements/development.txt
RUN pip install -r requirements/development.txt

COPY . .

EXPOSE 5000

# Gunicorn-managed uvicorn ASGI workers: keeps websockets, and recycles workers
# (--max-requests) so leaked DB connections/memory are reclaimed over time.
# docker-compose.prod.yml runs this; docker-compose.yml overrides it with
# runserver for local development.
CMD ["gunicorn", "master.asgi:application", "-k", "uvicorn_worker.UvicornWorker", "-b", "0.0.0.0:5000", "--workers", "3", "--max-requests", "800", "--max-requests-jitter", "200", "--timeout", "120", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
