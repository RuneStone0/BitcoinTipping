# BitcoinTipping.Org - A Bitcoin Tipping Jar Application

A Flask application for creating and managing digital tipping jars with SQLite database functionality.

## Setup

### Option 1: Docker (Recommended)

1. Install Docker and Docker Compose
2. Build and run the application:
   ```bash
   # Production mode
   docker-compose up --build
   
   # Development mode with hot reload
   docker-compose --profile dev up --build bitcoin-tipping-dev
   ```

### Option 2: Local Python Setup

1. Install Python 3.7 or higher
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

### Docker Commands

```bash
# Build the Docker image
docker build -t bitcoin-tipping .

# Run in production mode
docker run -p 5000:5000 -v $(pwd)/data:/app/data bitcoin-tipping

# Run in development mode
docker run -p 5000:5000 -v $(pwd):/app -v $(pwd)/data:/app/data bitcoin-tipping python app.py

# Using docker-compose (recommended)
docker-compose up --build
```

### Local Python Execution

#### Option 1: Direct Execution (Development)
1. Run the Flask application directly:
   ```bash
   python app.py
   ```

#### Option 2: Using Gunicorn (Production)
1. Run with Gunicorn:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```

   Or with more configuration options:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 --keep-alive 2 app:app
   ```

### Database Initialization
The database is automatically initialized when using Docker. For local development, initialize the database:
```bash
curl http://localhost:5000/init-db
```

Or visit `http://localhost:5000/init-db` in your browser.

### Database Migration
If you encounter database schema errors (e.g., "no such column"), you can migrate the database:
```bash
curl http://localhost:5000/migrate-db
```

**Warning:** This will reset all existing data and recreate the database with the latest schema.

### Docker Data Persistence
When using Docker, the database is stored in the `./data` directory on your host machine. This ensures your data persists between container restarts.

### Accessing the Application
Open your web browser and navigate to:
- `http://localhost:5000/` - Main interface with "Create Tipping Jar" button
- `http://localhost:5000/hello` - Shows "Hello from Flask!"
- `http://localhost:5000/init-db` - Initialize database with sample data
- `http://localhost:5000/jars` - View all jars (GET)
- `http://localhost:5000/jars/<id>` - View specific jar by ID (GET)
- `http://localhost:5000/jars/uuid/<uuid>` - View specific jar by UUID (GET)

### API Endpoints

#### Jars API
- **GET** `/jars` - Get all tipping jars
- **POST** `/jars` - Create a new tipping jar
  ```json
  {
    "email": "user@example.com"
  }
  ```
- **GET** `/jars/<id>` - Get jar by ID
- **GET** `/jars/uuid/<uuid>` - Get jar by UUID

#### Database Features
- SQLite database stored in `app.db` file
- Jar model with id, jar_uuid (auto-generated), email, and created_at fields
- Automatic database table creation
- Sample data initialization
- Web interface for creating tipping jars

**Note:** When running directly with `python app.py`, the application runs in debug mode and will automatically reload when you make changes to the code. Gunicorn is better suited for production deployments.


# TODO
* Security, changes must require email confirmation
* Print Preview as PDF