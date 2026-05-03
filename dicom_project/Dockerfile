FROM python:3.12-slim

# Install system dependencies needed for Python packages and psycopg2
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . /app/

# Make entrypoint script executable (might need dos2unix in windows, but we will make sure line endings are handled or sh works)
RUN chmod +x /app/entrypoint.sh

# Environment settings
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=dicom_project.settings

EXPOSE 8000

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
