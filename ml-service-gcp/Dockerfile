# ==============================
# Stage 1: Dependency builder
# ==============================

FROM python:3.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

# Install build tools needed only for Python packages that compile native extensions.
# These are not copied into the final runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       cmake \
       protobuf-compiler \
       libprotobuf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ==============================
# Stage 2: Runtime image
# ==============================

FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1

WORKDIR /app

# Install runtime libraries required by OpenCV/cv2.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1 \
       libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY app.py .
COPY inference.py .
COPY labels.txt .
COPY models/ ./models/

EXPOSE 8080

CMD exec gunicorn --bind 0.0.0.0:${PORT} --timeout 300 app:app
