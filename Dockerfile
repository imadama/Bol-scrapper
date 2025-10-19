# Gebruik Python 3.12 als basis image
FROM python:3.12-slim

# Stel werkdirectory in
WORKDIR /app

# Installeer systeem dependencies voor Playwright en Excel processing
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Kopieer requirements eerst (voor betere layer caching)
COPY requirements.txt .

# Installeer Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Installeer Playwright browsers
RUN playwright install chromium

# Kopieer de applicatie bestanden
COPY bol_scraper/ /app/bol_scraper/
COPY README.md /app/

# Maak directory voor data persistentie
RUN mkdir -p /app/bol_scraper/static/images/products

# Stel environment variabelen in
ENV FLASK_APP=bol_scraper/app.py
ENV PYTHONUNBUFFERED=1

# Expose Flask poort
EXPOSE 5000

# Verander naar de bol_scraper directory en start de app
WORKDIR /app/bol_scraper
CMD ["python", "app.py"]

