
# Lakeshore Creative Studios — Complete Build

Features:
- Booking system with availability checks
- Admin dashboard (login, cancel bookings, add new studios)
- SEO: meta tags, JSON-LD, robots.txt, sitemap.xml
- Branded responsive UI
- About & Contact pages
- ICS calendar export

## Run locally
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export FLASK_SECRET_KEY="choose-strong-secret"
export BUSINESS_URL="http://localhost:5000"
python app.py
