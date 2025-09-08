from flask import Flask, request, jsonify, render_template, send_file
from pymongo import MongoClient
import os
import uuid
import json
import qrcode
import io
import hashlib
from PIL import Image, ImageDraw
import bech32
import requests
from datetime import datetime, timedelta
from bson import ObjectId
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Database configuration
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/bitcoin_tipping')

# Extract database name from URI
def extract_database_name(uri):
    """Extract database name from MongoDB URI"""
    if '/' in uri and not uri.endswith('/'):
        return uri.split('/')[-1]
    return 'bitcoin_tipping'  # Default fallback

DATABASE_NAME = extract_database_name(MONGODB_URI)

# Initialize MongoDB connection
client = MongoClient(MONGODB_URI)
print(f"Using MongoDB at {MONGODB_URI}")

db = client[DATABASE_NAME]

# Database Collections
jars_collection = db.jars

# Helper functions for MongoDB operations
def generate_email_hash(email):
    """Generate SHA-256 hash of email address"""
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

def create_jar(email, payment_options=None, referral_codes=None):
    """Create a new jar document"""
    jar_doc = {
        'email': email,
        'email_hash': generate_email_hash(email),
        'payment_options': payment_options or {},
        'referral_codes': referral_codes or {},
        'created_at': datetime.utcnow()
    }
    result = jars_collection.insert_one(jar_doc)
    return result.inserted_id

def find_jar_by_email_hash(email_hash):
    """Find jar by email hash"""
    return jars_collection.find_one({'email_hash': email_hash})

def find_jar_by_email(email):
    """Find jar by email"""
    return jars_collection.find_one({'email': email})

def update_jar_payment_options(email_hash, payment_options):
    """Update jar payment options"""
    return jars_collection.update_one(
        {'email_hash': email_hash},
        {'$set': {'payment_options': payment_options}}
    )

def update_jar_referral_codes(email_hash, referral_codes):
    """Update jar referral codes"""
    return jars_collection.update_one(
        {'email_hash': email_hash},
        {'$set': {'referral_codes': referral_codes}}
    )

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/hello')
def hello():
    return 'Hello from Flask!'

@app.route('/health')
def health():
    """Health check endpoint for monitoring and load balancers"""
    from datetime import datetime
    try:
        # Test database connection
        client.admin.command('ping')
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'database_type': 'mongodb',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 503

@app.route('/jars', methods=['GET'])
def get_jars():
    jars = list(jars_collection.find())
    # Convert ObjectId to string for JSON serialization
    for jar in jars:
        jar['_id'] = str(jar['_id'])
        jar['created_at'] = jar['created_at'].isoformat() if jar.get('created_at') else None
    return jsonify(jars)

@app.route('/jars', methods=['POST'])
def create_jar_route():
    data = request.get_json()
    
    if not data or not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400
    
    # Check if jar already exists
    existing_jar = find_jar_by_email(data['email'])
    if existing_jar:
        return jsonify({'error': 'Jar already exists for this email'}), 400
    
    jar_id = create_jar(data['email'])
    jar = find_jar_by_email(data['email'])
    jar['_id'] = str(jar['_id'])
    jar['created_at'] = jar['created_at'].isoformat() if jar.get('created_at') else None
    
    return jsonify(jar), 201

@app.route('/jars/<jar_id>', methods=['GET'])
def get_jar(jar_id):
    try:
        jar = jars_collection.find_one({'_id': ObjectId(jar_id)})
        if not jar:
            return jsonify({'error': 'Jar not found'}), 404
        jar['_id'] = str(jar['_id'])
        jar['created_at'] = jar['created_at'].isoformat() if jar.get('created_at') else None
        return jsonify(jar)
    except Exception:
        return jsonify({'error': 'Invalid jar ID'}), 400

@app.route('/jars/hash/<email_hash>', methods=['GET'])
def get_jar_by_hash(email_hash):
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    jar['_id'] = str(jar['_id'])
    jar['created_at'] = jar['created_at'].isoformat() if jar.get('created_at') else None
    return jsonify(jar)

@app.route('/jars/hash/<email_hash>/payment-options', methods=['PUT'])
def update_payment_options(email_hash):
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    
    data = request.get_json()
    if not data or 'payment_options' not in data:
        return jsonify({'error': 'Payment options are required'}), 400
    
    update_jar_payment_options(email_hash, data['payment_options'])
    updated_jar = find_jar_by_email_hash(email_hash)
    updated_jar['_id'] = str(updated_jar['_id'])
    updated_jar['created_at'] = updated_jar['created_at'].isoformat() if updated_jar.get('created_at') else None
    
    return jsonify(updated_jar)

@app.route('/jars/hash/<email_hash>/referral-codes', methods=['PUT'])
def update_referral_codes(email_hash):
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    
    data = request.get_json()
    if not data or 'referral_codes' not in data:
        return jsonify({'error': 'Referral codes are required'}), 400
    
    update_jar_referral_codes(email_hash, data['referral_codes'])
    updated_jar = find_jar_by_email_hash(email_hash)
    updated_jar['_id'] = str(updated_jar['_id'])
    updated_jar['created_at'] = updated_jar['created_at'].isoformat() if updated_jar.get('created_at') else None
    
    return jsonify(updated_jar)


@app.route('/api/lnurl-pay/<email_hash>', methods=['GET'])
def get_lnurl_pay_string(email_hash):
    """Get Bech32-encoded LNURL-pay string for a jar's lightning address"""
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    
    payment_options = jar.get('payment_options', {})
    lightning_address = payment_options.get('lightning')
    if not lightning_address:
        return jsonify({'error': 'Lightning address not configured'}), 404
    
    lnurl_pay_string = lightning_address_to_lnurl_pay(lightning_address)
    return jsonify({'lnurl_pay': lnurl_pay_string})

@app.route('/api/bitcoin-price', methods=['GET'])
def get_bitcoin_price_api():
    """Get current Bitcoin price and conversion rates"""
    try:
        btc_price = get_bitcoin_price()
        return jsonify({
            'btc_price_usd': btc_price,
            'sats_per_usd': usd_to_sats(1),
            'usd_per_sat': round(1 / usd_to_sats(1), 8)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/qr/<email_hash>/<payment_method>', methods=['GET'])
def generate_qr_code(email_hash, payment_method):
    # Find jar by email_hash
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    
    payment_options = jar.get('payment_options', {})
    
    # Get amount parameter (default to 1 USD)
    amount_usd = request.args.get('amount', '1')
    try:
        amount_usd = float(amount_usd)
    except (ValueError, TypeError):
        amount_usd = 1.0
    
    # Handle special case for Bitcoin Core & Lightning
    if payment_method == 'bitcoin_core_lightning':
        bitcoin_address = payment_options.get('bitcoin')
        lightning_address = payment_options.get('lightning')
        
        if not bitcoin_address or not lightning_address:
            return jsonify({'error': 'Both Bitcoin and Lightning addresses are required for Bitcoin Core & Lightning'}), 404
        
        # Convert Lightning Address to Bech32-encoded LNURL-pay string
        lnurl_pay_string = lightning_address_to_lnurl_pay(lightning_address)
        
        # Convert USD to BTC using current Bitcoin price
        btc_price = get_bitcoin_price()
        btc_amount = amount_usd / btc_price
        
        # Create the combined bitcoin URI
        qr_data = f"bitcoin:{bitcoin_address}?amount={btc_amount:.8f}&lightning={lnurl_pay_string}"
    elif payment_method not in payment_options or not payment_options[payment_method]:
        return jsonify({'error': 'Payment method not found or not configured'}), 404
    else:
        # For individual payment methods, we don't modify the address
        # The amount is handled by the wallet when scanning the QR code
        qr_data = payment_options[payment_method]
    
    # Generate QR code with higher error correction to accommodate logo
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert PIL image to RGB if needed
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Get QR code dimensions
    qr_width, qr_height = img.size
    
    # Load and resize logo
    logo_size = min(qr_width, qr_height) // 5  # Logo is 1/5 of QR code size
    
    # Determine logo file based on payment method
    if payment_method == 'bitcoin':
        logo_path = "static/images/bitcoin.svg.png"
    elif payment_method == 'lightning':
        logo_path = "static/images/bitcoin-lightning.png"
    elif payment_method == 'bitcoin_core_lightning':
        logo_path = "static/images/bitcoin-lightning.png"  # Use lightning logo for combined method
    else:
        logo_path = None
    
    if logo_path and os.path.exists(logo_path):
        try:
            # Load the logo image
            logo_img = Image.open(logo_path)
            
            # Convert to RGB if needed
            if logo_img.mode != 'RGB':
                logo_img = logo_img.convert('RGB')
            
            # Resize logo to fit in QR code
            logo_img = logo_img.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            
            # Calculate position to center logo in QR code
            logo_x = (qr_width - logo_size) // 2
            logo_y = (qr_height - logo_size) // 2
            
            # Paste logo onto QR code
            img.paste(logo_img, (logo_x, logo_y))
            
        except Exception as e:
            # If logo loading fails, continue without logo
            print(f"Logo loading failed: {e}")
    
    # Convert to bytes
    img_io = io.BytesIO()
    img.save(img_io, format='PNG')
    img_io.seek(0)
    
    return send_file(img_io, mimetype='image/png')

@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400
    
    # Find jar by email
    jar = find_jar_by_email(data['email'])
    
    if jar:
        jar['_id'] = str(jar['_id'])
        jar['created_at'] = jar['created_at'].isoformat() if jar.get('created_at') else None
        return jsonify({'jar': jar})
    else:
        return jsonify({'error': 'No jar found with this email address'}), 404

@app.route('/manage/<email_hash>', methods=['GET'])
def jar_dashboard(email_hash):
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    return render_template('jar_dashboard.html', jar=jar)

@app.route('/jar/<email_hash>', methods=['GET'])
def public_jar(email_hash):
    # Find jar by email_hash
    jar = find_jar_by_email_hash(email_hash)
    if not jar:
        return jsonify({'error': 'Jar not found'}), 404
    return render_template('public_jar.html', jar=jar)

@app.route('/init-db')
def init_db():
    """Initialize the database with sample data"""
    messages = []
    
    # Show which database type is being used
    messages.append("Using mongodb database")
    
    # Always ensure dummy jar for rtk@rtk-cv.dk exists
    existing_dummy = find_jar_by_email('rtk@rtk-cv.dk')
    if not existing_dummy:
        # Create dummy jar for rtk@rtk-cv.dk
        dummy_jar_doc = {
            'email': 'rtk@rtk-cv.dk',
            'email_hash': generate_email_hash('rtk@rtk-cv.dk'),
            'payment_options': {
                "bitcoin": "bc1qf7flehxkfmmdvk0gxaqmrnfqs0srpvncrrv77u",
                "lightning": "runestone@strike.me",
            },
            'referral_codes': {
                "strike": "FDQH2P"
            },
            'created_at': datetime.utcnow()
        }
        jars_collection.insert_one(dummy_jar_doc)
        messages.append("Created dummy jar for rtk@rtk-cv.dk")
    else:
        messages.append("Dummy jar for rtk@rtk-cv.dk already exists")
    
    # Add sample jars if none exist (excluding the dummy jar)
    jar_count = jars_collection.count_documents({})
    if jar_count <= 1:  # Only dummy jar exists
        messages.append("Database initialized with sample data")
    else:
        messages.append(f"Database has {jar_count} jars")
    
    return jsonify({'message': '; '.join(messages)})

@app.route('/migrate-db')
def migrate_db():
    """MongoDB migration endpoint - no migration needed for MongoDB"""
    return jsonify({'message': 'MongoDB does not require schema migrations'})

def lightning_address_to_lnurl_pay(lightning_address):
    """Convert Lightning Address to Bech32-encoded LNURL-pay string"""
    if '@' not in lightning_address:
        # Assume it's already an LNURL or other format
        return lightning_address
    
    # Convert Lightning Address to LNURL endpoint
    username, domain = lightning_address.split('@', 1)
    lnurl_endpoint = f"https://{domain}/.well-known/lnurlp/{username}"
    
    # Convert to bytes and encode as Bech32
    lnurl_bytes = lnurl_endpoint.encode('utf-8')
    lnurl_pay_string = bech32.bech32_encode('lnurl', bech32.convertbits(lnurl_bytes, 8, 5))
    
    return lnurl_pay_string

def get_bitcoin_price():
    """Get current Bitcoin price in USD with 24-hour caching"""
    cache_file = os.path.join(app.root_path, 'bitcoin_price_cache.json')
    
    # Check if cache exists and is less than 24 hours old
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            if datetime.now() - cache_time < timedelta(hours=24):
                return cache_data['price']
        except (json.JSONDecodeError, KeyError, ValueError):
            # Cache file is corrupted, continue to fetch new price
            pass
    
    # Fetch new price from CoinGecko API
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd', timeout=10)
        response.raise_for_status()
        data = response.json()
        
        price = data['bitcoin']['usd']
        
        # Cache the price
        cache_data = {
            'price': price,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)
        
        return price
        
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"Error fetching Bitcoin price: {e}")
        # Return fallback price if API fails
        return 40000.0  # Conservative fallback

def usd_to_sats(usd_amount):
    """Convert USD amount to satoshis using current Bitcoin price"""
    btc_price = get_bitcoin_price()
    # 1 BTC = 100,000,000 sats
    sats = (usd_amount / btc_price) * 100_000_000
    return int(round(sats))

def sats_to_usd(sats_amount):
    """Convert satoshis to USD using current Bitcoin price"""
    btc_price = get_bitcoin_price()
    # 1 BTC = 100,000,000 sats
    usd = (sats_amount / 100_000_000) * btc_price
    return round(usd, 2)

# For Gunicorn deployment
def create_app():
    return app

if __name__ == '__main__':
    # MongoDB collections are created automatically when first accessed
    app.run(debug=True, host='0.0.0.0', port=5000)
