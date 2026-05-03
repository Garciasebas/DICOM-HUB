#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
while ! nc -z db 5432; do
  sleep 1
done
echo "PostgreSQL is up - starting Django"

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn server..."
exec gunicorn dicom_project.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 2 --timeout 300
