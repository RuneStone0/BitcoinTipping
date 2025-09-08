#!/bin/bash
set -e

# Wait for MongoDB to be ready
echo "Waiting for MongoDB to be ready..."
python -c "
import time
import os
from pymongo import MongoClient

mongodb_uri = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/bitcoin_tipping')
max_retries = 30
retry_count = 0

while retry_count < max_retries:
    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=2000)
        client.server_info()  # This will raise an exception if MongoDB is not ready
        print('MongoDB is ready!')
        break
    except Exception as e:
        retry_count += 1
        print(f'MongoDB not ready yet, retrying... ({retry_count}/{max_retries})')
        time.sleep(2)

if retry_count >= max_retries:
    print('Failed to connect to MongoDB after maximum retries')
    exit(1)
"

echo "Starting Bitcoin Tipping application..."

echo "Starting application..."

# Execute the main command
exec "$@"
