FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/cache/huggingface PYTHONPATH=/srv
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 sox ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt /tmp/requirements.txt
RUN printf 'torch==2.6.0\ntorchaudio==2.6.0\nnumpy==1.26.4\nhuggingface-hub==0.36.0\n' > /tmp/constraints.txt \
    && pip install -c /tmp/constraints.txt torchaudio==2.6.0 qwen-tts==0.1.1 -r /tmp/requirements.txt
COPY app /srv/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
