# 🐳 Docker Instructies - Bol Scraper

Deze handleiding laat je zien hoe je de Bol Scraper kunt draaien met Docker Desktop.

## 📋 Vereisten

- Docker Desktop geïnstalleerd en draaiend
- Minimaal 2GB vrije RAM
- Minimaal 2GB vrije schijfruimte

## 🚀 Snelstart

### Optie 1: Met Docker Compose (Aanbevolen)

```bash
# 1. Ga naar de project directory
cd /Users/emi/Documents/GitHub/Bol-scrapper

# 2. Build en start de container
docker-compose up --build

# 3. Open je browser en ga naar:
# http://localhost:5001
```

De applicatie is nu klaar voor gebruik! 🎉

### Optie 2: Met Docker commands

```bash
# 1. Build de image
docker build -t bol-scraper .

# 2. Run de container
docker run -d \
  --name bol-scraper \
  -p 5001:5000 \
  -v $(pwd)/bol_scraper:/app/bol_scraper \
  bol-scraper

# 3. Open je browser en ga naar:
# http://localhost:5001
```

## 🎮 Container Beheer

### Status controleren
```bash
# Via Docker Compose
docker-compose ps

# Of direct met Docker
docker ps
```

### Logs bekijken
```bash
# Via Docker Compose (live logs)
docker-compose logs -f

# Of direct met Docker
docker logs -f bol-scraper-app
```

### Container stoppen
```bash
# Via Docker Compose
docker-compose down

# Of direct met Docker
docker stop bol-scraper
```

### Container herstarten
```bash
# Via Docker Compose
docker-compose restart

# Of direct met Docker
docker restart bol-scraper
```

### Container verwijderen
```bash
# Via Docker Compose (inclusief volumes)
docker-compose down -v

# Of direct met Docker
docker stop bol-scraper
docker rm bol-scraper
```

## ⚙️ Configuratie

### Environment Variabelen

Maak een `.env` bestand aan in de root directory:

```bash
cp .env.example .env
```

Bewerk het `.env` bestand naar wens:

```env
FLASK_SECRET_KEY=jouw-geheime-sleutel-hier
HEADLESS=true
OUTPUT_EXCEL=scraped_products.xlsx
FLASK_DEBUG=0
```

### Poort aanpassen

De applicatie draait standaard op poort **5001** (omdat 5000 vaak al in gebruik is op macOS).

Als je een andere poort wilt gebruiken, pas deze aan in `docker-compose.yml`:

```yaml
ports:
  - "8080:5000"  # Verander 5001 naar een andere poort
```

## 💾 Data Persistentie

De volgende data wordt automatisch bewaard:

- **Excel bestanden**: Opgeslagen in `bol_scraper/` directory
- **Afbeeldingen**: Opgeslagen in Docker volume `scraped-data`
- **Template bestand**: `Export_generic_template_20251004_07 PM052.xlsx`

Als je de container verwijdert, blijven je Excel bestanden bewaard!

## 🔧 Troubleshooting

### Container start niet

```bash
# Controleer of poort 5001 al in gebruik is
lsof -i :5001  # Mac/Linux
netstat -ano | findstr :5001  # Windows

# Bekijk gedetailleerde logs
docker-compose logs
```

### Browser timeout errors

Als Playwright timeouts geeft:
1. Verhoog geheugen in Docker Desktop (Settings > Resources)
2. Zorg dat je een stabiele internetverbinding hebt
3. Probeer `HEADLESS=false` in `.env` voor debugging

### Schijfruimte problemen

```bash
# Ruim oude Docker images op
docker system prune -a

# Verwijder ongebruikte volumes
docker volume prune
```

### Permission errors (Linux)

```bash
# Voer uit met sudo of voeg jezelf toe aan docker groep
sudo usermod -aG docker $USER
# Log daarna opnieuw in
```

## 🔄 Updates

Als je de code aanpast:

```bash
# Via Docker Compose
docker-compose up --build

# Of rebuild de image
docker-compose build --no-cache
docker-compose up
```

## 🐞 Debug Mode

Voor development met live logs:

```bash
# Draai in foreground mode
docker-compose up

# Of met meer verbose logging
FLASK_DEBUG=1 docker-compose up
```

## 📊 Docker Desktop Interface

Je kunt ook Docker Desktop gebruiken voor visueel beheer:

1. Open Docker Desktop
2. Ga naar "Containers"
3. Vind "bol-scraper-app"
4. Gebruik de knoppen voor:
   - ▶️ Start
   - ⏸️ Stop
   - 🔄 Restart
   - 📋 Logs bekijken
   - 🗑️ Verwijderen

## 🌐 Toegang vanaf andere apparaten

Als je de app wilt openen vanaf andere computers in je netwerk:

1. Vind je lokale IP adres:
```bash
# Mac/Linux
ipconfig getifaddr en0

# Windows
ipconfig
```

2. Open op andere apparaat:
```
http://JE-IP-ADRES:5001
```

**Let op**: Zorg dat je firewall poort 5001 toestaat.

## 📝 Best Practices

1. **Backups**: Maak regelmatig backups van je Excel bestanden
2. **Updates**: Update de Docker image regelmatig voor security patches
3. **Resources**: Monitor geheugengebruik in Docker Desktop
4. **Logs**: Check logs regelmatig voor errors
5. **Secrets**: Gebruik nooit echte secrets in `.env` voor productie

## 🆘 Hulp Nodig?

Als je problemen hebt:

1. Check de logs: `docker-compose logs`
2. Verifieer dat Docker Desktop draait
3. Controleer of poort 5001 beschikbaar is
4. Test of je internet verbinding stabiel is
5. Probeer de container opnieuw te builden: `docker-compose up --build`

---

**Veel succes met scrapen! 🚀**

