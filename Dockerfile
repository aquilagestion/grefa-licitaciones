FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run ejecuta el contenedor como usuario sin privilegios.
# HOME se fija explícitamente porque Streamlit busca los secretos en
# ~/.streamlit/secrets.toml, que es donde Cloud Run monta el volumen de
# Secret Manager (montarlo en /app/.streamlit ocultaría config.toml).
RUN useradd --create-home --uid 1000 grefa \
    && mkdir -p /home/grefa/.streamlit \
    && chown -R grefa:grefa /app /home/grefa
ENV HOME=/home/grefa
USER grefa

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/_stcore/health" || exit 1

CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
