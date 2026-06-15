FROM debian:13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3-full \
       build-essential \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create virtual environment
RUN python3 -m venv /app/venv

# Upgrade pip and install dependencies in venv
COPY requirements.txt ./
RUN /app/venv/bin/pip install --upgrade pip setuptools wheel \
    && /app/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd --gid 1000 pashtet \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash pashtet \
    && mkdir -p /data \
    && chown -R pashtet:pashtet /app /data

USER pashtet

CMD ["/app/venv/bin/python3", "bot.py"]
