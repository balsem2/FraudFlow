FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 fraudflow \
    && mkdir /state && chown fraudflow:fraudflow /state
COPY requirements-lock.txt .
RUN python -m pip install -r requirements-lock.txt
COPY fraudflow ./fraudflow
COPY app.py .
COPY .streamlit/config.toml ./.streamlit/config.toml
USER fraudflow
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.headless", "true"]
