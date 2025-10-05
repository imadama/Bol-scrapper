# Gebruik Python 3.11 slim image
FROM python:3.11-slim

# Stel werkdirectory in
WORKDIR /app

# Installeer systeem dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Kopieer requirements eerst voor betere Docker cache
COPY requirements.txt .

# Installeer Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Installeer Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Kopieer applicatie code
COPY . .

# Maak directories voor afbeeldingen en Excel bestanden
RUN mkdir -p static/images/products

# Stel environment variabelen in
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=bol_scraper/app.py
ENV FLASK_ENV=production
ENV HEADLESS=true

# Expose port
EXPOSE 5000

# Maak entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Start de applicatie
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "bol_scraper/app.py"]
