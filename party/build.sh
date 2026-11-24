#!/usr/bin/env bash
# Збірка для Render (або будь-якого Linux-хостингу).
set -o errexit -o nounset -o pipefail

# Залежності з хешами: підмінений пакет у PyPI не встановиться.
pip install --upgrade pip
pip install --require-hashes -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py check --deploy --fail-level WARNING
