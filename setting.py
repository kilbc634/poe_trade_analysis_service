import os

REDIS_HOST = os.getenv('REDIS_HOST', '172.17.0.1')
REDIS_AUTH = os.getenv('REDIS_AUTH', 'cv*****')
BROKER_URL = os.getenv('BROKER_URL', f'redis://:{REDIS_AUTH}@{REDIS_HOST}:6379/0')
SERVICE_HOST = os.getenv('SERVICE_HOST', 'http://tsukumonet.ddns.net:16666/')
