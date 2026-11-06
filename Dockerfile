FROM python:3.13-slim
COPY server /app
WORKDIR /app
ENV ENGRAM_DB=/data/engram.db PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8443
CMD ["python3", "server.py"]
