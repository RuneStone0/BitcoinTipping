from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
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

app = Flask(__name__)

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "app.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Database Models
class Jar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    email_hash = db.Column(db.String(64), unique=True, nullable=False)  # SHA-256 hash of email
    payment_options = db.Column(db.Text, default='[]')  # JSON string of payment options
    referral_codes = db.Column(db.Text, default='{}')  # JSON string of referral codes
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __init__(self, email, **kwargs):
        super(Jar, self).__init__(**kwargs)
        self.email = email
        self.email_hash = self._generate_email_hash(email)

    def _generate_email_hash(self, email):
        """Generate SHA-256 hash of email address"""
        return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

    def __repr__(self):
        return f'<Jar {self.email_hash}>'

    def get_payment_options(self):
        try:
            return json.loads(self.payment_options)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_payment_options(self, options):
        self.payment_options = json.dumps(options)

    def get_referral_codes(self):
        try:
            return json.loads(self.referral_codes)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_referral_codes(self, codes):
        self.referral_codes = json.dumps(codes)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'email_hash': self.email_hash,
            'payment_options': self.get_payment_options(),
            'referral_codes': self.get_referral_codes(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

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
    from sqlalchemy import text
    try:
        # Test database connection
        db.session.execute(text('SELECT 1'))
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
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
    jars = Jar.query.all()
    return jsonify([jar.to_dict() for jar in jars])

@app.route('/jars', methods=['POST'])
def create_jar():
    data = request.get_json()
    
    if not data or not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400
    
    jar = Jar(email=data['email'])
    db.session.add(jar)
    db.session.commit()
    
    return jsonify(jar.to_dict()), 201

@app.route('/jars/<int:jar_id>', methods=['GET'])
def get_jar(jar_id):
    jar = Jar.query.get_or_404(jar_id)
    return jsonify(jar.to_dict())

@app.route('/jars/hash/<email_hash>', methods=['GET'])
def get_jar_by_hash(email_hash):
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    return jsonify(jar.to_dict())

@app.route('/jars/hash/<email_hash>/payment-options', methods=['PUT'])
def update_payment_options(email_hash):
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    data = request.get_json()
    
    if not data or 'payment_options' not in data:
        return jsonify({'error': 'Payment options are required'}), 400
    
    jar.set_payment_options(data['payment_options'])
    db.session.commit()
    
    return jsonify(jar.to_dict())

@app.route('/jars/hash/<email_hash>/referral-codes', methods=['PUT'])
def update_referral_codes(email_hash):
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    data = request.get_json()
    
    if not data or 'referral_codes' not in data:
        return jsonify({'error': 'Referral codes are required'}), 400
    
    jar.set_referral_codes(data['referral_codes'])
    db.session.commit()
    
    return jsonify(jar.to_dict())


@app.route('/api/lnurl-pay/<email_hash>', methods=['GET'])
def get_lnurl_pay_string(email_hash):
    """Get Bech32-encoded LNURL-pay string for a jar's lightning address"""
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    payment_options = jar.get_payment_options()
    
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
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    payment_options = jar.get_payment_options()
    
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
    jar = Jar.query.filter_by(email=data['email']).first()
    
    if jar:
        return jsonify({'jar': jar.to_dict()})
    else:
        return jsonify({'error': 'No jar found with this email address'}), 404

@app.route('/manage/<email_hash>', methods=['GET'])
def jar_dashboard(email_hash):
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    return render_template('jar_dashboard.html', jar=jar)

@app.route('/jar/<email_hash>', methods=['GET'])
def public_jar(email_hash):
    # Find jar by email_hash
    jar = Jar.query.filter_by(email_hash=email_hash).first_or_404()
    # Ensure payment_options and referral_codes are parsed for the template
    jar.payment_options = jar.get_payment_options()
    jar.referral_codes = jar.get_referral_codes()
    return render_template('public_jar.html', jar=jar)

@app.route('/init-db')
def init_db():
    """Initialize the database with sample data"""
    db.create_all()
    
    messages = []
    
    # Always ensure dummy jar for rtk@rtk-cv.dk exists
    existing_dummy = Jar.query.filter_by(email='rtk@rtk-cv.dk').first()
    if not existing_dummy:
        # Create dummy jar for rtk@rtk-cv.dk
        dummy_jar = Jar(email='rtk@rtk-cv.dk')
        dummy_jar.set_payment_options({
            "bitcoin": "bc1qf7flehxkfmmdvk0gxaqmrnfqs0srpvncrrv77u",
            "lightning": "runestone@strike.me",
        })
        dummy_jar.set_referral_codes({
            "strike": "FDQH2P"
        })
        db.session.add(dummy_jar)
        db.session.commit()
        messages.append("Created dummy jar for rtk@rtk-cv.dk")
    else:
        messages.append("Dummy jar for rtk@rtk-cv.dk already exists")
    
    # Add sample jars if none exist (excluding the dummy jar)
    jar_count = Jar.query.count()
    if jar_count <= 1:  # Only dummy jar exists
        messages.append("Database initialized with sample data")
    else:
        messages.append(f"Database has {jar_count} jars")
    
    return jsonify({'message': '; '.join(messages)})

@app.route('/migrate-db')
def migrate_db():
    """Migrate existing database to new schema"""
    try:
        from sqlalchemy import text
        result = db.session.execute(text("PRAGMA table_info(jar)"))
        columns = [row[1] for row in result.fetchall()]
        column_names = [row[1] for row in result.fetchall()]
        
        migrations_applied = []
        
        # Check if email_hash column exists, if not add it
        if 'email_hash' not in column_names:
            db.session.execute(text("ALTER TABLE jar ADD COLUMN email_hash TEXT"))
            db.session.commit()
            migrations_applied.append("Added email_hash column")
            
            # Populate email_hash for existing records
            existing_jars = db.session.execute(text("SELECT id, email FROM jar")).fetchall()
            for jar_id, email in existing_jars:
                email_hash = generate_email_hash(email)
                db.session.execute(text("UPDATE jar SET email_hash = :hash WHERE id = :id"), 
                                 {"hash": email_hash, "id": jar_id})
            db.session.commit()
            migrations_applied.append("Populated email_hash for existing records")
        
        # Check if referral_codes column exists, if not add it
        if 'referral_codes' not in column_names:
            db.session.execute(text("ALTER TABLE jar ADD COLUMN referral_codes TEXT DEFAULT '{}'"))
            db.session.commit()
            migrations_applied.append("Added referral_codes column")
        
        # Drop old UUID columns if they exist (they're no longer needed)
        if 'jar_uuid' in column_names:
            # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
            # First, backup existing data
            existing_data = db.session.execute(text("SELECT id, email, email_hash, payment_options, referral_codes, created_at FROM jar")).fetchall()
            
            # Drop the old table
            db.session.execute(text("DROP TABLE jar"))
            db.session.commit()
            
            # Create the new table with the correct schema
            db.create_all()
            
            # Restore the data
            for row in existing_data:
                db.session.execute(text("""
                    INSERT INTO jar (id, email, email_hash, payment_options, referral_codes, created_at) 
                    VALUES (:id, :email, :email_hash, :payment_options, :referral_codes, :created_at)
                """), {
                    "id": row[0],
                    "email": row[1], 
                    "email_hash": row[2],
                    "payment_options": row[3],
                    "referral_codes": row[4],
                    "created_at": row[5]
                })
            db.session.commit()
            migrations_applied.append("Removed old UUID columns and recreated table")
        
        if migrations_applied:
            return jsonify({'message': f'Database migrated successfully. Applied: {", ".join(migrations_applied)}'})
        else:
            return jsonify({'message': 'Database is already up to date.'})
    except Exception as e:
        return jsonify({'error': f'Migration failed: {str(e)}'}), 500

# Helper function to generate email hash (useful for migrations)
def generate_email_hash(email):
    """Generate SHA-256 hash of email address"""
    return hashlib.sha256(email.lower().encode('utf-8')).hexdigest()

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
    cache_file = os.path.join(basedir, 'bitcoin_price_cache.json')
    
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
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
