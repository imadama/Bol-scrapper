# ⚡ Snelle Start - Server Deployment

Quick reference voor het deployen van Bol Scraper op een server.

## 🎯 In 10 Minuten Live

### Voorbereiding
- [ ] VPS server met Ubuntu (bijv. DigitalOcean €6/maand)
- [ ] Domein met A-record naar server IP
- [ ] SSH toegang tot server

---

## 📋 Commando's Kopiëren & Plakken

### 1️⃣ Server Setup (5 min)

```bash
# SSH naar server
ssh root@JE-SERVER-IP

# Installeer alles in 1 keer
sudo apt update && sudo apt upgrade -y && \
curl -fsSL https://get.docker.com -o get-docker.sh && \
sudo sh get-docker.sh && \
sudo apt install docker-compose nginx certbot python3-certbot-nginx git -y && \
sudo usermod -aG docker $USER

# Verifieer
docker --version && nginx -v
```

### 2️⃣ Code Deployen (2 min)

```bash
# Clone repository
cd ~
git clone https://github.com/JOUW-USERNAME/Bol-scrapper.git
cd Bol-scrapper

# Maak .env bestand
nano .env
```

Plak dit in `.env`:
```env
FLASK_SECRET_KEY=PLAK-HIER-RANDOM-STRING
HEADLESS=true
OUTPUT_EXCEL=scraped_products.xlsx
FLASK_DEBUG=0
PUBLIC_BASE_URL=https://scraper.jouwdomein.nl
```

Genereer secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3️⃣ Nginx Configureren (2 min)

```bash
# Maak Nginx config
sudo nano /etc/nginx/sites-available/bol-scraper
```

Plak dit (vervang `scraper.jouwdomein.nl`):
```nginx
server {
    listen 80;
    server_name scraper.jouwdomein.nl;
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }

    location /static {
        alias /root/Bol-scrapper/bol_scraper/static;
        expires 30d;
    }
}
```

Activeer:
```bash
sudo ln -s /etc/nginx/sites-available/bol-scraper /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 4️⃣ SSL Installeren (1 min)

```bash
sudo certbot --nginx -d scraper.jouwdomein.nl
# Volg prompts, kies optie 2 voor HTTPS redirect
```

### 5️⃣ Start Applicatie (30 sec)

```bash
cd ~/Bol-scrapper
docker-compose -f docker-compose.prod.yml up -d --build
```

---

## ✅ Test

Open browser:
```
https://scraper.jouwdomein.nl
```

Je zou nu de Bol Scraper moeten zien! 🎉

---

## 🔧 Handige Commando's

```bash
# Logs bekijken
docker-compose -f docker-compose.prod.yml logs -f

# Herstarten
docker-compose -f docker-compose.prod.yml restart

# Stoppen
docker-compose -f docker-compose.prod.yml down

# Updaten na code wijziging
cd ~/Bol-scrapper
git pull
docker-compose -f docker-compose.prod.yml up -d --build
```

---

## 🛡️ Basis Beveiliging (Optioneel, +2 min)

```bash
# Firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
```

---

## 💡 Tips

1. **DNS Propagatie**: Kan 5-30 minuten duren. Test met `nslookup scraper.jouwdomein.nl`
2. **Public Base URL**: Moet exact matchen met je domein in `.env`
3. **Backups**: Excel bestanden staan in `~/Bol-scrapper/bol_scraper/`
4. **Monitoring**: Gebruik `htop` en `docker stats`

---

## 🆘 Problemen?

### Domein bereikt server niet
```bash
nslookup scraper.jouwdomein.nl
sudo ufw status
```

### Container draait niet
```bash
docker ps
docker-compose -f docker-compose.prod.yml logs
```

### Nginx errors
```bash
sudo nginx -t
sudo tail -f /var/log/nginx/error.log
```

---

**Meer details? Zie [PRODUCTIE_DEPLOYMENT.md](PRODUCTIE_DEPLOYMENT.md)**

