# =============================================================================
# Prop Firm Trading Bot — Docker Image
# =============================================================================
# Build:
#   docker build -t prop-firm-bot .
# Run:
#   docker run -d -p 8080:8080 --env-file .env --name bot prop-firm-bot
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="trading-bot@example.com"
LABEL description="Prop Firm Trading Bot with FastAPI dashboard"

# Prevent Python from writing .pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory inside the container
WORKDIR /app

# Install system dependencies (if needed by MetaTrader5 or other packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source code into the container
COPY . .

# Expose the FastAPI dashboard port
EXPOSE 8080

# Health check for container orchestrators
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run the trading bot
CMD ["python", "main.py"]
