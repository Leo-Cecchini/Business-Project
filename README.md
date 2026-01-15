# Build Flow AI

**Build Flow AI** is our project for the course "Business and Project Management" of the Master Degree in Artificial Intelligence and Data Engineering of the University of Pisa. The primary objective was to implement a business-oriented system that utilize GenAI in an innovative way.
We built a comprehensive, enterprise-grade solution designed to support construction site management through AI. By integrating traditional project management workflows with a Retrieval-Augmented Generation (RAG) architecture, this platform serves as an intelligent bridge between complex technical documentation and daily field operations. 

This platform centralizes project specifications, work catalogs, and workforce data to address the common issue of fragmented information in the construction industry. The system utilizes natural language processing to allow site managers to directly query technical estimates (Computo Metrico Estimativo), check labor availability, and generate cost projections. By automating these lookups, the platform provides data-driven insights for calculating margins on work items and identifying available personnel by region.

🇮🇹 Keep in mind that our project is built for the italian construction systems, especially regarding the estimation feature that is based on italian regulations (computo metrico estimativo).

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
* `/seed`: Initial datasets including material catalogs, price lists, and worker profiles (in italian) for system initialization.
* `/models`: Custom implementations for the vector store and the underlying LLM interfaces.

## Initial Setup

**0. Google API Key**

You'll need a Google API Key to be added to the file .env

0.1 Open https://aistudio.google.com/api-keys

0.2 Log-in with your Google account

0.3 Click on "Create API Key"

0.4 Create a new project with the name that you prefer (doesn't matter)

0.5 Click on "Create key"

0.6 Now you'll have to click on the "Gemini API Key" on the row which has just appeared and you'll se entire API key

0.7 In the file `.env` (in the main folder), ```"GOOGLE_API_KEY=your_google_api_key"``` replace ```"your_google_api_key"``` with your key 

**1. Import and create Docker containers**

First install Docker (https://docs.docker.com/desktop/, scroll down and select your OS).
Open Docker
```bash
git clone <repo-url>
cd Business-Project
docker-compose up --build
```

**2. Access the frontend for the user interface**
**Frontend:** http://localhost:5173  
Backend API: http://localhost:5001

**3. Optional**
In the folder `./seed` there are some initial datasets (all of them are AI generated) in italian for populating the database. 
To load them you can use the script `init_db.py` in the main folder.

**4. Enjoy!**

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

## To modify the code

**Frontend/Backend:** Save file → automatic hot reload

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
