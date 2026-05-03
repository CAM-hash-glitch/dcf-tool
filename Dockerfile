FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY dcf.py main.py ./

# Most platforms set $PORT; default to 8000 for local docker run
ENV PORT=8000
EXPOSE 8000

# Use shell form so $PORT expands
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
