FROM python:3.13-slim
COPY server/server.py /app/
COPY server/site /app/site
WORKDIR /app
ENV ENGRAM_DB=/data/engram.db PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8443
CMD ["python3", "server.py"]
