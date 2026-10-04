FROM python:3.12-alpine
WORKDIR /app
COPY app.py ./
ARG MODE=good
ENV MODE=$MODE PORT=8080
CMD ["python", "-u", "app.py"]
