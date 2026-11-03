FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/cache/huggingface \
    PYTHONPATH=/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:/srv
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential ffmpeg libsndfile1 sox libgomp1 \
    && rm -rf /var/lib/apt/lists/*
ARG COSY_COMMIT=074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
RUN git clone --filter=blob:none https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice \
    && cd /opt/CosyVoice && git checkout "$COSY_COMMIT" \
    && git submodule update --init --recursive
WORKDIR /srv
COPY requirements.txt docker/cosy-requirements.txt /tmp/
# No CUDA ONNX wheel or Chinese/English text normalizer on ARM CPU.
# Korean inference uses text_frontend=False, as in the GPU experiment.
RUN sed '/^onnxruntime-gpu==/d; /^wetext==/d' /tmp/cosy-requirements.txt > /tmp/cosy-cpu.txt \
    && printf 'torch==2.6.0\ntorchaudio==2.6.0\nnumpy==1.26.4\nsetuptools==75.8.0\n' > /tmp/constraints.txt \
    && PIP_CONSTRAINT=/tmp/constraints.txt pip install -c /tmp/constraints.txt \
       torch==2.6.0 torchaudio==2.6.0 onnxruntime==1.20.1 \
       -r /tmp/requirements.txt -r /tmp/cosy-cpu.txt gdown==5.1.0 matplotlib==3.7.5
COPY app /srv/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
