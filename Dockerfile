FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
# Local knowledge base: used when RAG_BACKEND=local, and for its version hash.
COPY knowledge_base ./knowledge_base
RUN useradd -m app && mkdir -p data && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "pr_review_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
