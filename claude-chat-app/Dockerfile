FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for file processing and health checks
# RUN apt-get update && apt-get install -y \
#     curl \
#     && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
# This includes: app.py, auth.py, utils/, .streamlit/
COPY . .

EXPOSE 8501

#HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8502/chat/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.baseUrlPath=/chat", \
     "--server.headless=true"]
