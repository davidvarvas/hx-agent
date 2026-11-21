# Base image pinned by exact version and digest so every rebuild gets the same image.
FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
# One math-library thread: the container gets a single CPU.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
# Wheels only: fail fast instead of compiling numpy from source.
RUN pip install --no-cache-dir --only-binary=:all: numpy==2.1.3
WORKDIR /bot
COPY wire.py nav.py bot.py ./
RUN python3 -m compileall -q /bot
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
