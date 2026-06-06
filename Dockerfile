FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install minimal font packages and set up a non-root user for safer container runtime
RUN apt-get update \
	&& apt-get install -y --no-install-recommends fonts-dejavu-core fontconfig \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python-bot/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create non-root user that matches the VPS user used by the Docker stack
RUN groupadd --gid 1000 pashtet \
	&& useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash pashtet \
	&& mkdir -p /app /data \
	&& chown -R pashtet:pashtet /app /data

COPY python-bot/ /app/

USER pashtet

CMD ["python", "bot.py"]
