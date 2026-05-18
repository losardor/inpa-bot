FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 inpa \
 && useradd  --system --uid 1000 --gid inpa \
             --home-dir /app --shell /usr/sbin/nologin inpa

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/

RUN mkdir -p /app/data && chown -R inpa:inpa /app

USER inpa

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.scheduler"]
