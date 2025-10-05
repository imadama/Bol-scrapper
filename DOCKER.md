# 🐳 Docker Deployment Guide

## Quick Start

### 1. Development (Local)
```bash
# Build en start de applicatie
docker compose up --build

# Of in de achtergrond
docker compose up -d --build
```

De applicatie is beschikbaar op: http://localhost:5000

### 2. Production (met Nginx)
```bash
# Start met Nginx reverse proxy
docker compose --profile production up -d --build
```

De applicatie is beschikbaar op: http://localhost:80

## Configuratie

### Environment Variabelen
Kopieer `env.template` naar `.env` en pas aan:

```bash
cp env.template .env
nano .env
```

Belangrijke instellingen:
- `FLASK_SECRET_KEY`: Wijzig dit voor productie!
- `IMAGE_BASE_URL`: Voor productie, vervang met je publieke domein

### Volumes
De volgende directories worden persistent opgeslagen:
- `./data` - Excel bestanden en data
- `./static` - Afbeeldingen
- `./bol_scraper` - Template bestanden

## Commands

### Development
```bash
# Start applicatie
docker compose up

# Stop applicatie
docker compose down

# Rebuild na code changes
docker compose up --build

# Bekijk logs
docker compose logs -f bol-scraper
```

### Production
```bash
# Start met Nginx
docker compose --profile production up -d

# Stop alles
docker compose --profile production down

# Update applicatie
docker compose --profile production pull
docker compose --profile production up -d --build
```

## Troubleshooting

### Playwright browsers niet geïnstalleerd
```bash
docker compose exec bol-scraper python -m playwright install chromium
```

### Permission issues
```bash
# Fix file permissions
sudo chown -R $USER:$USER ./data ./static
```

### Container niet start
```bash
# Bekijk logs
docker compose logs bol-scraper

# Start interactief
docker compose run --rm bol-scraper bash
```

## Security

### Voor productie:
1. Wijzig `FLASK_SECRET_KEY`
2. Stel `IMAGE_BASE_URL` in naar je publieke domein
3. Configureer SSL certificaten in nginx
4. Gebruik een firewall
5. Update regelmatig de Docker images

### SSL Setup (optioneel)
```bash
# Plaats SSL certificaten in ./ssl/
mkdir ssl
# Kopieer je certificaten:
# - ssl/cert.pem
# - ssl/key.pem

# Update nginx.conf voor HTTPS
```

## Monitoring

### Health Check
```bash
# Controleer of applicatie draait
curl http://localhost:5000/

# Via nginx
curl http://localhost/health
```

### Logs
```bash
# Bekijk real-time logs
docker compose logs -f

# Bekijk logs van specifieke service
docker compose logs -f bol-scraper
```

## Backup

### Data backup
```bash
# Backup alle data
tar -czf backup-$(date +%Y%m%d).tar.gz data/ static/ bol_scraper/

# Restore
tar -xzf backup-YYYYMMDD.tar.gz
```

## Performance

### Resource limits
Voeg toe aan `docker-compose.yml`:
```yaml
services:
  bol-scraper:
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'
```

### Scaling (optioneel)
```bash
# Scale de applicatie (let op: sessie data wordt niet gedeeld)
docker compose up --scale bol-scraper=3
```
