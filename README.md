# Build Flow AI

**Build Flow AI** is our project for the course "Business and Project Management" of the Master Degree in Artificial Intelligence and Data Engineering of the University of Pisa. The primary objective was to implement a business-oriented system that utilize GenAI in an innovative way.
We built a comprehensive, enterprise-grade solution designed to support construction site management through AI. By integrating traditional project management workflows with a Retrieval-Augmented Generation (RAG) architecture, this platform serves as an intelligent bridge between complex technical documentation and daily field operations. 

This platform centralizes project specifications, work catalogs, and workforce data to address the common issue of fragmented information in the construction industry. The system utilizes natural language processing to allow site managers to directly query technical estimates (Computo Metrico Estimativo), check labor availability, and generate cost projections. By automating these lookups, the platform provides data-driven insights for calculating margins on work items and identifying available personnel by region.

🇮🇹 Keep in mind that our project is built for the italian construction systems, especially regarding the estimation feature that is based on italian regulations.

## 🛠️ Tech Stack
### Backend
* **Framework**: Flask (Python)
* **AI Orchestration**: LangChain
* **LLM Integration**: Google Gemini
* **Primary Database**: MongoDB (via MongoEngine)
* **Vector Database**: Qdrant

### Frontend
* **Library**: React (Vite)
* **State Management**: React Query
* **Styling**: Tailwind CSS

## 📂 Project Structure

* `/backend`: Contains the Flask API, AI service logic, intent routers, and database models.
* `/frontend`: The React application including specialized dashboards for company-wide and site-specific chat interfaces.
* `/seed`: Initial datasets including material catalogs, price lists, and worker profiles for system initialization.
* `/models`: Custom implementations for the vector store and the underlying LLM interfaces.

## Initial Setup

```bash
git clone <repo-url>
cd Business-Project-5
docker-compose up --build
```


**Frontend:** http://localhost:5173  
**Backend API:** http://localhost:5001

---

## Basic Commands

```bash
# Start
docker-compose up

# Background start
docker-compose up -d

# Stop
docker-compose down

# Service Restart
docker-compose restart backend
docker-compose restart frontend

# Logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

---

## Modify Code

**Frontend/Backend:** Salva file → automatic hot reload

**Changed dependencies (package.json / requirements.txt):**
```bash
docker-compose up --build frontend
docker-compose up --build backend
```

---

## Database

**MongoDB Access:**
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

## Problems

**Occupied port:**
```bash
netstat -ano | findstr :5001
taskkill /PID <PID> /F
```

**Complete rebuild:**
```bash
docker-compose down -v
docker-compose build --no-cache
docker-compose up
```

**Full Reset:**
```bash
docker-compose down -v
docker system prune -a
docker-compose up --build
```

---

## Credentials

**MongoDB:** admin / changeme123
