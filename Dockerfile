# Gebruik officiële Playwright Python image (bevat Python, Playwright, system deps en browsers)
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

# Stel werkdirectory in
WORKDIR /app

# Kopieer requirements
COPY requirements.txt .

# Installeer Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Installeer WebKit expliciet (voor zekerheid)
RUN playwright install webkit

# Kopieer de applicatie bestanden
COPY bol_scraper/ /app/bol_scraper/
COPY README.md /app/

# Maak directory voor data persistentie
RUN mkdir -p /app/bol_scraper/static/images/products

# Stel environment variabelen in
ENV FLASK_APP=bol_scraper/app.py
ENV PYTHONUNBUFFERED=1
ENV PORT=5002

# Expose Flask poort
EXPOSE 5002

# Verander naar de bol_scraper directory en start de app
WORKDIR /app/bol_scraper
CMD ["python", "app.py"]

