FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000 SUDMS_INSTANCE_PATH=/var/data/sudms SUDMS_HTTPS=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-thai-tlwg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
RUN mkdir -p /var/data/sudms
EXPOSE 10000
CMD ["python", "serve.py"]
