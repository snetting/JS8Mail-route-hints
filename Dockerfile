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
CMD ["js8mail-route-hints"]
