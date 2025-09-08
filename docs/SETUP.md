# Setup Instructions

## Quick Start

### Option 1: Docker (Recommended)

1. Install Docker and Docker Compose
2. Run the application:
   ```bash
   docker-compose up --build
   ```

### Option 2: Local Development

1. Install Python 3.7+ and MongoDB
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start MongoDB:
   ```bash
   mongosh --eval "db.runCommand('ping')"
   ```
4. Run the application:
   ```bash
   python app.py
   ```

## Configuration

The application uses a `.env` file for configuration. Copy `.env.example` to `.env` and adjust as needed.

### Key Environment Variables

- `MONGODB_URI=mongodb://localhost:27017/bitcoin_tipping` - Database connection
- `FLASK_ENV=development` - Flask environment
- `SECRET_KEY=your-secret-key` - Flask secret key

## Database Setup

Visit `http://localhost:5000/init-db` to initialize the database with sample data.

## Access the Application

- **Home**: http://localhost:5000
- **Health Check**: http://localhost:5000/health

## Production Deployment

For production, use Gunicorn:
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```
