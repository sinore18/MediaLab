FROM bleeper-server-runtime:latest

WORKDIR /app/server
COPY --chown=app:app src ./src

USER app
EXPOSE 8000

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
