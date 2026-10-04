# Running pocketful (stage 1)

The service is pure Python standard library — no external packages, no
build-time network fetch needed beyond pulling the base image.

## Build

```
docker build -t pocketful-stage1 .
```

## Run

```
docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage1
```

The container listens on `0.0.0.0:$PORT` (default `8080` if `PORT` is
unset) and serves `GET /health` -> `200 {"status": "ok"}` once ready.

## Run the tests against it

```
cd /home/prashant/projects/band-work/result
BASE_URL=http://127.0.0.1:8080 .venv/bin/python -m pytest stage-1/tests -q
```
