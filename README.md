# ⚙️ JanSetu — Civic Intelligence & Municipal Operations Backend API

[![Django](https://img.shields.io/badge/Django-5.1-darkgreen)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/Django%20REST%20Framework-3.15-red)](https://www.django-rest-framework.org/)
[![JWT](https://img.shields.io/badge/Auth-SimpleJWT%20(HttpOnly)-orange)](https://django-rest-framework-simplejwt.readthedocs.io/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)

> **JanSetu** is the high-performance Django REST backend powering the JanSeva civic platform. It provides automated AI duplicate detection, geospatial distance calculations, JWT HttpOnly cookie management, closed-loop resolution enforcement, and relational persistence.

---

## 🌟 Core Backend Capabilities

1. **🤖 Spatial AI Duplicate Auto-Merger**:
   - Computes great-circle Haversine distance and string lexical similarity between new and existing tickets.
   - Automatically merges duplicates within 200m into a single high-priority ticket while preserving upvotes and reporter XP.

2. **🔄 Closed-Loop Resolution Protocol**:
   - Enforces a 5-stage ticket lifecycle (`Reported` -> `AI Verified` -> `Squad Dispatched` -> `In Progress` -> `Pending Citizen Verification` -> `Verified Resolved`).
   - Prevents premature resolution without verified citizen on-ground photo audits.

3. **🔒 Robust JWT & Security Architecture**:
   - Dual-token authentication with Access tokens and secure `HttpOnly` refresh cookies (`janseva_refresh`).
   - Department security access code validation for municipal engineers.

4. **⚡ Flexible Issue Identifier Resolution**:
   - Seamlessly resolves tickets whether queried by numeric ID (`111`), prefixed string (`JS-111`), or slug.

---

## 📡 Key REST Endpoints

- **Auth**: `/api/auth/login/`, `/api/auth/register/`, `/api/auth/google/`, `/api/auth/token/refresh/cookie/`
- **Issues**: `/api/issues/`, `/api/issues/<id>/`, `/api/issues/<id>/status/`, `/api/issues/<id>/assign/`, `/api/issues/<id>/upvote/`, `/api/issues/<id>/verify/`, `/api/issues/merge/`
- **Governance**: `/api/polls/`, `/api/budgets/`, `/api/announcements/`, `/api/leaderboard/`

---

## 🚀 Local Setup

```bash
# 1. Activate virtual environment
python -m venv venv
.\venv\Scripts\activate   # Windows
source venv/bin/activate # macOS/Linux

# 2. Install dependencies
pip install django djangorestframework djangorestframework-simplejwt django-cors-headers pillow python-dotenv requests

# 3. Apply migrations and run
python manage.py migrate
python manage.py runserver
```

---

## 📜 License

MIT License.
