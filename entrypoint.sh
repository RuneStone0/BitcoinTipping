#!/bin/bash
set -e

# Create data directory if it doesn't exist
mkdir -p /app/data

# Wait for any initialization to complete
echo "Starting Bitcoin Tipping application..."

# Initialize database if it doesn't exist
if [ ! -f /app/data/app.db ]; then
    echo "Initializing database..."
    python -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Database created successfully')
"
fi

# Run database migration if needed
echo "Running database migration..."
python -c "
from app import app, db
from sqlalchemy import text
import hashlib

def generate_email_hash(email):
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

with app.app_context():
    try:
        # Check if email_hash column exists
        result = db.session.execute(text('PRAGMA table_info(jar)'))
        columns = [row[1] for row in result.fetchall()]
        
        migrations_applied = []
        
        # Check if email_hash column exists, if not add it
        if 'email_hash' not in columns:
            db.session.execute(text('ALTER TABLE jar ADD COLUMN email_hash TEXT'))
            db.session.commit()
            migrations_applied.append('Added email_hash column')
            
            # Populate email_hash for existing records
            existing_jars = db.session.execute(text('SELECT id, email FROM jar')).fetchall()
            for jar_id, email in existing_jars:
                email_hash = generate_email_hash(email)
                db.session.execute(text('UPDATE jar SET email_hash = :hash WHERE id = :id'), 
                                 {'hash': email_hash, 'id': jar_id})
            db.session.commit()
            migrations_applied.append('Populated email_hash for existing records')
        
        # Check if referral_codes column exists, if not add it
        if 'referral_codes' not in columns:
            db.session.execute(text('ALTER TABLE jar ADD COLUMN referral_codes TEXT DEFAULT \"{}\"'))
            db.session.commit()
            migrations_applied.append('Added referral_codes column')
        
        if migrations_applied:
            print(f'Migration applied: {migrations_applied}')
        else:
            print('Database is already up to date')
    except Exception as e:
        print(f'Migration completed with note: {e}')
"

# Initialize with sample data
echo "Initializing sample data..."
python -c "
from app import app, db, Jar
import json

with app.app_context():
    try:
        # Always ensure dummy jar for rtk@rtk-cv.dk exists
        existing_dummy = Jar.query.filter_by(email='rtk@rtk-cv.dk').first()
        if not existing_dummy:
            # Create dummy jar for rtk@rtk-cv.dk
            dummy_jar = Jar(email='rtk@rtk-cv.dk')
            dummy_jar.set_payment_options({
                'bitcoin': 'bc1qf7flehxkfmmdvk0gxaqmrnfqs0srpvncrrv77u',
                'lightning': 'runestone@strike.me',
            })
            dummy_jar.set_referral_codes({
                'strike': 'FDQH2P'
            })
            db.session.add(dummy_jar)
            db.session.commit()
            print('Created dummy jar for rtk@rtk-cv.dk')
        else:
            print('Dummy jar for rtk@rtk-cv.dk already exists')
        
        jar_count = Jar.query.count()
        print(f'Database has {jar_count} jars')
    except Exception as e:
        print(f'Sample data initialization completed with note: {e}')
"

echo "Starting application..."

# Execute the main command
exec "$@"
