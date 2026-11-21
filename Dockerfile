# The match runs this image with no network, a read-only root (writable /tmp), 1 CPU, 512 MB,
# as uid 65534, with the map mounted at /arena.
# Base image pinned by exact version and digest: finalists are rebuilt later and must get this same image.
FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
# One math-library thread: the match allows 1 CPU and 128 threads, and numpy's OpenBLAS would otherwise
# start a thread per host core on a big scoring machine.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
# Wheels only: if the pinned wheel were ever missing, fail fast instead of compiling numpy past the 10-minute limit.
RUN pip install --no-cache-dir --only-binary=:all: numpy==2.1.3
WORKDIR /bot
COPY wire.py nav.py bot.py ./
RUN python3 -m compileall -q /bot
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
