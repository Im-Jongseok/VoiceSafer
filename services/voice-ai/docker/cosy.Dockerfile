FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/cache/huggingface \
    PYTHONPATH=/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:/srv
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential ffmpeg libsndfile1 sox \
    && rm -rf /var/lib/apt/lists/*
ARG COSY_COMMIT=074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
RUN git clone --filter=blob:none https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice \
    && cd /opt/CosyVoice && git checkout "$COSY_COMMIT" \
    && git submodule update --init --recursive
WORKDIR /srv
COPY requirements.txt docker/cosy-requirements.txt /tmp/
RUN printf 'torch==2.6.0\ntorchaudio==2.6.0\nnumpy==1.26.4\nsetuptools==75.8.0\n' > /tmp/constraints.txt \
    && PIP_CONSTRAINT=/tmp/constraints.txt pip install -c /tmp/constraints.txt torchaudio==2.6.0 -r /tmp/requirements.txt -r /tmp/cosy-requirements.txt
# Matcha imports its utility module during model construction.
RUN pip install gdown==5.1.0 matplotlib==3.7.5
# ONNX Runtime dlopen needs cuDNN's split libraries on the search path.
ENV LD_LIBRARY_PATH=/opt/conda/lib/python3.11/site-packages/nvidia/cudnn/lib:/opt/conda/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/conda/lib/python3.11/site-packages/nvidia/cuda_runtime/lib:/opt/conda/lib:${LD_LIBRARY_PATH}
COPY app /srv/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
