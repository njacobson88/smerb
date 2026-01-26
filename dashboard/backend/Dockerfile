# SocialScope Dashboard Backend
# Dockerfile for Cloud Run deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create exports directory
RUN mkdir -p /app/exports

# Set environment variables
ENV PORT=8080
ENV HOST=0.0.0.0
ENV DEV_MODE=false

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
