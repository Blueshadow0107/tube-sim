FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py graph.py solver.py timeline.py ./
COPY static static
COPY templates templates
COPY data data
# one worker: the network graph is cached in-process; threads handle concurrency.
# long timeout: /api/challenge/solve runs a search with a ~25 s budget.
CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 120"]
