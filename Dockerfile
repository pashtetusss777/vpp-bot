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

# Create non-root user and set permissions
RUN useradd --create-home --shell /bin/bash appuser \
	&& mkdir -p /app /data \
	&& chown -R appuser:appuser /app /data

COPY python-bot/ /app/

USER appuser

CMD ["python", "bot.py"]
