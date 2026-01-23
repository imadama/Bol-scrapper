# 🚀 Productie Deployment Guide - Bol Scraper

Complete handleiding voor het draaien van de Bol Scraper op een server met Docker en domein.

## 📋 Vereisten

### Server
- VPS/Cloud server (bijv. DigitalOcean, Hetzner, AWS, Google Cloud)
- Ubuntu 20.04+ of Debian 11+ (aanbevolen)
- Minimaal 2GB RAM
- 20GB schijfruimte
- Root/sudo toegang

### Domein
- Een geregistreerd domein (bijv. `mijndomein.nl`)
- Toegang tot DNS instellingen

### Lokaal
- SSH client
- Git (voor code deployment)

---

## 🔧 Stap 1: Server Voorbereiden

### 1.1 Verbind met je server via SSH

```bash
ssh root@JE-SERVER-IP
# of
ssh gebruiker@JE-SERVER-IP
```

### 1.2 Update systeem

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.3 Installeer Docker & Docker Compose

```bash
# Installeer Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Installeer Docker Compose
sudo apt install docker-compose -y

# Voeg je gebruiker toe aan docker groep (herstart sessie daarna)
sudo usermod -aG docker $USER

# Verifieer installatie
docker --version
docker-compose --version
```

### 1.4 Installeer Nginx (voor reverse proxy)

```bash
sudo apt install nginx -y
```

### 1.5 Installeer Certbot (voor gratis SSL)

```bash
sudo apt install certbot python3-certbot-nginx -y
```

---

## 🌐 Stap 2: DNS Configureren

### 2.1 Voeg A-record toe in je DNS provider

Log in bij je domein provider (bijv. Namecheap, Cloudflare, TransIP) en voeg toe:

```
Type: A
Name: @ (of scraper voor scraper.mijndomein.nl)
Value: JE-SERVER-IP
TTL: 3600
```

**Voorbeelden:**
- `scraper.mijndomein.nl` → A record met naam `scraper`
- `mijndomein.nl` → A record met naam `@`

### 2.2 Wacht op DNS propagatie

```bash
# Test of DNS werkt (kan 5-30 minuten duren)
nslookup scraper.ttbanden.nl
```

---

## 📦 Stap 3: Code Deployen

### 3.1 Clone repository op server

```bash
# Ga naar home directory
cd ~

# Clone je repository
git clone https://github.com/JOUW-USERNAME/Bol-scrapper.git
cd Bol-scrapper
```


Voeg toe:

```env
# Productie configuratie
FLASK_SECRET_KEY=GENEREER-LANGE-RANDOM-STRING-HIER
HEADLESS=true
OUTPUT_EXCEL=scraped_products.xlsx
FLASK_DEBUG=0
PUBLIC_BASE_URL=https://scraper.ttbanden.nl
```

**Genereer veilige secret key:**

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3.3 Maak productie Docker Compose

Maak een nieuw bestand `docker-compose.prod.yml`:

```bash
nano docker-compose.prod.yml
```

```yaml
services:
  bol-scraper:
    build: .
    container_name: bol-scraper-app
    ports:
      - "127.0.0.1:5000:5000"  # Alleen lokaal, Nginx proxied ernaartoe
    environment:
      - FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
      - HEADLESS=${HEADLESS:-true}
      - OUTPUT_EXCEL=${OUTPUT_EXCEL:-scraped_products.xlsx}
      - FLASK_DEBUG=0
      - PUBLIC_BASE_URL=${PUBLIC_BASE_URL}
    volumes:
      - ./bol_scraper:/app/bol_scraper
      - ./bol_scraper/static/images/products:/app/bol_scraper/static/images/products
    restart: always
    networks:
      - bol-scraper-network

networks:
  bol-scraper-network:
    driver: bridge
```

---

## 🔒 Stap 4: Nginx Reverse Proxy Configureren

### 4.1 Maak Nginx configuratie

```bash
sudo nano /etc/nginx/sites-available/bol-scraper
```

Voeg toe:

```nginx
server {
    listen 80;
    server_name scraper.mijndomein.nl;  # Vervang met jouw domein

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts voor scraping
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }

    location /static {
        alias /root/Bol-scrapper/bol_scraper/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 4.2 Activeer configuratie

```bash
# Maak symlink
sudo ln -s /etc/nginx/sites-available/bol-scraper /etc/nginx/sites-enabled/

# Test configuratie
sudo nginx -t

# Herstart Nginx
sudo systemctl restart nginx
```

---

## 🔐 Stap 5: SSL Certificaat Installeren (HTTPS)

### 5.1 Verkrijg gratis SSL certificaat met Certbot

```bash
sudo certbot --nginx -d scraper.ttbanden.nl
```

Volg de prompts:
- Voer je email in
- Accepteer Terms of Service
- Kies optie 2 voor automatische HTTPS redirect

### 5.2 Test automatische vernieuwing

```bash
sudo certbot renew --dry-run
```

---

## 🚀 Stap 6: Start de Applicatie

### 6.1 Build en start Docker containers

```bash
cd ~/Bol-scrapper

# Build en start met productie compose
docker-compose -f docker-compose.prod.yml up -d --build

# Check logs
docker-compose -f docker-compose.prod.yml logs -f
```

### 6.2 Verifieer dat alles werkt

```bash
# Check of container draait
docker ps

# Test lokaal
curl http://localhost:5000

# Test via domein
curl https://scraper.mijndomein.nl
```

---

## 🎉 Stap 7: Test de Applicatie

Open in je browser:

```
https://scraper.mijndomein.nl
```

Je zou nu:
- ✅ De Bol Scraper UI moeten zien
- ✅ HTTPS (groene hangslot) moeten hebben
- ✅ Producten moeten kunnen scrapen
- ✅ Afbeeldingen URLs moeten zijn: `https://scraper.mijndomein.nl/static/images/products/...`

---

## 🔧 Beheer & Onderhoud

### Logs bekijken

```bash
cd ~/Bol-scrapper

# Live logs
docker-compose -f docker-compose.prod.yml logs -f

# Laatste 100 regels
docker-compose -f docker-compose.prod.yml logs --tail=100
```

### Container herstarten

```bash
docker-compose -f docker-compose.prod.yml restart
```

### Code updaten

```bash
cd ~/Bol-scrapper

# Pull laatste wijzigingen
git pull

# Rebuild en herstart
docker-compose -f docker-compose.prod.yml up -d --build
```

### Backup maken

```bash
# Backup Excel bestanden en afbeeldingen
cd ~/Bol-scrapper
tar -czf backup-$(date +%Y%m%d).tar.gz bol_scraper/*.xlsx bol_scraper/static/images/products/

# Download naar lokaal
scp root@JE-SERVER-IP:~/Bol-scrapper/backup-*.tar.gz ~/Desktop/
```

### Container stoppen

```bash
docker-compose -f docker-compose.prod.yml down
```

---

## 🛡️ Beveiliging (Aanbevolen)

### 1. Firewall instellen

```bash
# Installeer UFW
sudo apt install ufw -y

# Configureer firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https

# Activeer firewall
sudo ufw enable

# Check status
sudo ufw status
```

### 2. Basic Auth toevoegen (optioneel)

Voor extra beveiliging, voeg password bescherming toe:

```bash
# Installeer apache2-utils
sudo apt install apache2-utils -y

# Maak wachtwoord bestand
sudo htpasswd -c /etc/nginx/.htpasswd admin
```

Update Nginx config:

```nginx
location / {
    auth_basic "Restricted Access";
    auth_basic_user_file /etc/nginx/.htpasswd;
    
    proxy_pass http://127.0.0.1:5000;
    # ... rest van config
}
```

Herstart Nginx:

```bash
sudo systemctl restart nginx
```

### 3. SSH beveiliging

```bash
# Bewerk SSH config
sudo nano /etc/ssh/sshd_config

# Verander deze instellingen:
PermitRootLogin no
PasswordAuthentication no  # Gebruik alleen SSH keys

# Herstart SSH
sudo systemctl restart sshd
```

---

## 📊 Monitoring (Optioneel)

### Server resource monitoring

```bash
# Installeer htop
sudo apt install htop -y

# Monitor CPU/RAM
htop

# Check disk usage
df -h

# Docker stats
docker stats
```

### Automatische backups instellen

Maak backup script:

```bash
nano ~/backup.sh
```

```bash
#!/bin/bash
cd ~/Bol-scrapper
BACKUP_DIR=~/backups
mkdir -p $BACKUP_DIR

# Maak backup
tar -czf $BACKUP_DIR/backup-$(date +%Y%m%d-%H%M).tar.gz \
    bol_scraper/*.xlsx \
    bol_scraper/static/images/products/

# Verwijder backups ouder dan 7 dagen
find $BACKUP_DIR -name "backup-*.tar.gz" -mtime +7 -delete
```

Maak uitvoerbaar en voeg toe aan crontab:

```bash
chmod +x ~/backup.sh

# Voeg toe aan crontab (dagelijks om 3:00)
crontab -e

# Voeg toe:
0 3 * * * ~/backup.sh
```

---

## 🐛 Troubleshooting

### Container start niet

```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs

# Check of poort al in gebruik is
sudo netstat -tulpn | grep :5000
```

### Nginx errors

```bash
# Check Nginx status
sudo systemctl status nginx

# Check error logs
sudo tail -f /var/log/nginx/error.log

# Test configuratie
sudo nginx -t
```

### SSL problemen

```bash
# Vernieuw certificaat handmatig
sudo certbot renew

# Check certificaat status
sudo certbot certificates
```

### Domein bereikt server niet

```bash
# Test DNS
nslookup scraper.mijndomein.nl

# Test of Nginx werkt
curl -I http://JE-SERVER-IP

# Check firewall
sudo ufw status
```

---

## 💰 Geschatte Kosten

### Server opties:
- **DigitalOcean Droplet**: €6-12/maand (2GB RAM)
- **Hetzner Cloud**: €4-8/maand (2GB RAM)
- **Contabo VPS**: €5-7/maand (4GB RAM)
- **AWS/Google Cloud**: €10-20/maand (variabel)

### Domein:
- **TransIP**: €5-10/jaar (.nl domein)
- **Namecheap**: €8-15/jaar (.com domein)
- **Cloudflare**: €10-12/jaar + gratis SSL/CDN

### SSL Certificaat:
- **Let's Encrypt**: Gratis! ✅

**Totaal: ~€10-25/maand**

---

## 📝 Checklist voor Go-Live

- [ ] Server draait en is toegankelijk via SSH
- [ ] Docker & Docker Compose geïnstalleerd
- [ ] Nginx geïnstalleerd en draait
- [ ] DNS A-record ingesteld en propagated
- [ ] Repository gedeployed naar server
- [ ] `.env` bestand met productie settings
- [ ] Docker container draait (`docker ps`)
- [ ] Nginx reverse proxy geconfigureerd
- [ ] SSL certificaat geïnstalleerd en HTTPS werkt
- [ ] Applicatie toegankelijk via `https://jouwdomein.nl`
- [ ] Afbeeldingen worden gedownload naar `/static`
- [ ] Image URLs zijn volledig: `https://jouwdomein.nl/static/...`
- [ ] Firewall geconfigureerd
- [ ] Backups ingesteld
- [ ] Monitoring actief

---

## 🆘 Hulp Nodig?

### Handige commando's

```bash
# SSH verbinding
ssh root@JE-SERVER-IP

# Naar project directory
cd ~/Bol-scrapper

# Logs bekijken
docker-compose -f docker-compose.prod.yml logs -f

# Container herstarten
docker-compose -f docker-compose.prod.yml restart

# Nginx herstarten
sudo systemctl restart nginx

# SSL vernieuwen
sudo certbot renew
```

### Resources
- Docker Docs: https://docs.docker.com/
- Nginx Docs: https://nginx.org/en/docs/
- Let's Encrypt: https://letsencrypt.org/
- DigitalOcean Tutorials: https://www.digitalocean.com/community/tutorials

---

**Succes met je deployment! 🚀**

