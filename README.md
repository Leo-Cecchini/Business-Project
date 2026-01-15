# Business Project

## Setup Iniziale

```bash
git clone <repo-url>
cd Business-Project-5
docker-compose up --build
```


**Frontend:** http://localhost:5173  
**Backend API:** http://localhost:5001

---

## Comandi Base

```bash
# Avvio
docker-compose up

# Avvio in background
docker-compose up -d

# Stop
docker-compose down

# Restart servizio
docker-compose restart backend
docker-compose restart frontend

# Logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

---

## Modifiche Codice

**Frontend/Backend:** Salva file → hot reload automatico

**Dipendenze cambiate (package.json / requirements.txt):**
```bash
docker-compose up --build frontend
docker-compose up --build backend
```

---

## Database

**Accesso MongoDB:**
```bash
docker-compose exec mongodb mongosh -u admin -p changeme123
use business_project
db.projects.find()
exit
```

**Reset DB:**
```bash
docker-compose down -v
docker-compose up
```

**Re-seed:**
```bash
docker-compose exec mongodb mongosh -u admin -p changeme123 business_project --eval "db.materials.deleteMany({});"
docker-compose restart backend
```

---

## Problemi

**Port occupata:**
```bash
netstat -ano | findstr :5001
taskkill /PID <PID> /F
```

**Rebuild completo:**
```bash
docker-compose down -v
docker-compose build --no-cache
docker-compose up
```

**Reset totale:**
```bash
docker-compose down -v
docker system prune -a
docker-compose up --build
```

---

## Credenziali

**MongoDB:** admin / changeme123