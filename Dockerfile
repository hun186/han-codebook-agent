FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir 'PyYAML>=6.0,<7'
COPY src ./src
COPY examples ./examples
COPY config.yaml config.offline.yaml ./
ENV PYTHONPATH=/app/src
ENTRYPOINT ["python", "-m", "han_codebook"]
CMD ["--config", "config.offline.yaml"]
