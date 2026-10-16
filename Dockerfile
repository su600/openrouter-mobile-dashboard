FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --system --uid 10001 --create-home dashboard \
    && mkdir -p /data \
    && chown 10001:10001 /data

COPY --chown=10001:10001 . /app
RUN pip install --no-cache-dir requests \
    && for file in config.json accounts.json runtime_keys.json widget_readonly_token github_copilot_accounts.json daily_baseline.json dashboard_note.txt; do \
         ln -s "/data/$file" "/app/$file"; \
       done

USER 10001:10001
EXPOSE 9000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/healthz', timeout=3)" || exit 1
CMD ["python", "server.py"]
