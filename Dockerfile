# For running the engine and its tests on a computer without Python (the daily job
# runs on GitHub's own Linux machines instead).
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq libexpat1 >/dev/null && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /work
