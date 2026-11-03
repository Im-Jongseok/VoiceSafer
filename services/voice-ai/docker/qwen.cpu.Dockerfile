FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/cache/huggingface PYTHONPATH=/srv
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 sox ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt /tmp/requirements.txt
RUN pip install torch==2.6.0 torchaudio==2.6.0 numpy==1.26.4 huggingface-hub==0.36.0 \
    qwen-tts==0.1.1 -r /tmp/requirements.txt
COPY app /srv/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
