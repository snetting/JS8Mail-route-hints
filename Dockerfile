FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV ROUTE_HINTS_HOST=0.0.0.0
ENV ROUTE_HINTS_PORT=8787
ENV ROUTE_HINTS_DATABASE=/data/route-hints.sqlite3

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

VOLUME ["/data"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('ROUTE_HINTS_PORT', '8787') + '/healthz', timeout=3).read()"]
CMD ["js8mail-route-hints"]
