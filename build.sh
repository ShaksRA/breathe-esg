#!/usr/bin/env bash
# build.sh — Render/Railway build script
# Builds the React frontend and copies it into Django's static directory
# so Django/whitenoise can serve the SPA from a single process.

set -e

echo "=== Installing Python dependencies ==="
pip install -r backend/requirements.txt

echo "=== Installing Node dependencies ==="
cd frontend
npm ci

echo "=== Building React app ==="
REACT_APP_API_URL="" npm run build

echo "=== Copying React build into Django static ==="
cd ..
mkdir -p backend/static
cp -r frontend/build/. backend/static/
# The index.html needs to be in Django's template dirs so TemplateView finds it
mkdir -p backend/templates
cp frontend/build/index.html backend/templates/index.html

echo "=== Running Django migrations ==="
cd backend
python manage.py migrate --noinput

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput

echo "=== Seeding demo data ==="
python manage.py seed_demo || echo "Seed already done or failed — continuing"

echo "=== Build complete ==="
