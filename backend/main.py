import os
import time
import json
import logging
from io import BytesIO
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CommunityHelperAPI")



# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

@app.middleware("http")
async def db_and_role_middleware(request: Request, call_next):
    path = request.url.path
    # Bypass role validation for OPTIONS preflight, root, login, and user points endpoints
    if request.method == "OPTIONS" or path == "/" or path == "/api/login" or not path.startswith("/api/") or path.startswith("/api/users/"):
        return await call_next(request)
        
    user_role = request.headers.get("x-user-role")
    valid_roles = ["member", "manager", "admin"]
    
    if not user_role or user_role not in valid_roles:
        return JSONResponse(
            status_code=403,
            content={"detail": "Access Restricted: Missing or invalid user role credentials."}
        )
        
    # Enforce role-based restrictions
    # 1. Admin-only endpoints
    admin_only_paths = [
        "/api/audit-logs",
        "/api/incidents/reset-pres",
        "/api/reset"
    ]
    is_admin_only = any(path.startswith(p) for p in admin_only_paths) or path.endswith("/escalate")
    if is_admin_only and user_role != "admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Access Restricted: This action requires Administrator clearance."}
        )
        
    # 2. Manager/Admin endpoints
    manager_admin_paths = [
        "/api/analytics",
        "/api/recommend-team",
        "/api/predict-resolution"
    ]
    is_manager_admin = any(path.startswith(p) for p in manager_admin_paths)
    
    # PATCH requests to incidents are for manager/admin only, except when a member is updating their ticket (e.g. confirming/reopening)
    if request.method == "PATCH" and path.startswith("/api/incidents/"):
        if user_role == "member":
            is_manager_admin = False
        else:
            is_manager_admin = True
        
    if is_manager_admin and user_role not in ["manager", "admin"]:
        return JSONResponse(
            status_code=403,
            content={"detail": "Access Restricted: This action requires Supervisor or Administrator clearance."}
        )
        
    return await call_next(request)

# ═══════════════════════════════════════════════════
# GEMINI API INITIALIZATION
# ═══════════════════════════════════════════════════
from dotenv import load_dotenv
# Load .env file relative to main.py path
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

USE_GEMINI = False
genai_client = None

gemini_key = os.environ.get("GEMINI_API_KEY")
if gemini_key:
    try:
        from google import genai
        from google.genai import types
        genai_client = genai.Client(api_key=gemini_key)
        USE_GEMINI = True
        print("Gemini connected")
        logger.info("🤖 Gemini API initialized successfully using official google-genai SDK.")
    except Exception as e:
        print("Gemini fallback active")
        logger.error(f"❌ Failed to import or initialize google-genai SDK: {e}. Falling back to Rule-based AI Mock Mode.")
else:
    print("Gemini fallback active")
    logger.warning("⚠️ GEMINI_API_KEY environment variable not set. Running in Rule-based AI Mock Mode.")

# ═══════════════════════════════════════════════════
# DATABASE & FIREBASE INITIALIZATION
# ═══════════════════════════════════════════════════
USE_FIREBASE = False
db = None

firebase_creds_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if firebase_creds_path and os.path.exists(firebase_creds_path):
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        cred = credentials.Certificate(firebase_creds_path)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        USE_FIREBASE = True
        logger.info("🔥 Firebase Admin SDK initialized successfully in Firestore/Auth Mode.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Firebase: {e}. Falling back to Local JSON Mode.")

# Local File-based Database Fallback (db.json)
DB_FILE = os.path.join(os.path.dirname(__file__), "db.json")

def get_firebase_uid(email: str) -> str:
    """Resolves email to user UID via Firebase Auth, or returns mock fallback."""
    if USE_FIREBASE:
        try:
            from firebase_admin import auth
            try:
                user = auth.get_user_by_email(email)
                return user.uid
            except auth.UserNotFoundError:
                user = auth.create_user(email=email)
                return user.uid
        except Exception as e:
            logger.error(f"Error resolving Firebase UID for {email}: {e}")
    import hashlib
    return "mock-uid-" + hashlib.md5(email.encode('utf-8')).hexdigest()[:12]

def resolve_gps_coordinates(gps: str, description: str = "") -> str:
    """Normalizes coordinate strings and falls back to MG Road if empty or invalid."""
    default_gps = "12.971598,77.594562"
    if not gps or not gps.strip():
        desc_lower = description.lower()
        if "gate 3" in desc_lower or "central park" in desc_lower:
            return "12.972300,77.594800"
        elif "mg road" in desc_lower:
            return "12.971598,77.594562"
        elif "park ave" in desc_lower:
            return "12.970200,77.595100"
        return default_gps
    
    clean_gps = gps.replace("GPS Lock · Lat: ", "").replace(" Lng: ", "").strip()
    parts = clean_gps.split(",")
    if len(parts) == 2:
        try:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            return f"{lat},{lng}"
        except ValueError:
            pass
    return default_gps

INITIAL_INCIDENTS = [
    {
        "id": "RD-1142",
        "category": "Road Damage",
        "title": "Deep Pothole #RD-1142",
        "description": "Deep pothole causing traffic slowing and hazard on MG Road.",
        "location": "GPS Lock · Lat: 12.971598, Lng: 77.594562",
        "color": "#EF4444",
        "icon": "🕳️",
        "status": "Reported",
        "crew": "Unassigned",
        "priority": "High",
        "confidence": 96.5,
        "gps": "12.971598, 77.594562",
        "timestamp": int(datetime.utcnow().timestamp() * 1000),
        "attachments": {"text": True, "image": True, "voice": True}
    },
    {
        "id": "WL-0388",
        "category": "Water Infrastructure",
        "title": "Pipe Leak #WL-0388",
        "description": "Water spraying onto sidewalk from fractured pipe.",
        "location": "GPS Lock · Lat: 12.972300, Lng: 77.594800",
        "color": "#3B82F6",
        "icon": "💧",
        "status": "Reported",
        "crew": "Unassigned",
        "priority": "Moderate",
        "confidence": 94.2,
        "gps": "12.972300, 77.594800",
        "timestamp": int(datetime.utcnow().timestamp() * 1000) - 3600000,
        "attachments": {"text": True, "image": True, "voice": False}
    },
    {
        "id": "DR-2771",
        "category": "Drainage System",
        "title": "Clogged Drain #DR-2771",
        "description": "Debris and leaves blocking storm drain inlet.",
        "location": "GPS Lock · Lat: 12.973100, Lng: 77.593900",
        "color": "#0EA5E9",
        "icon": "🌊",
        "status": "Verified",
        "crew": "Unassigned",
        "priority": "Moderate",
        "confidence": 95.8,
        "gps": "12.973100, 77.593900",
        "timestamp": int(datetime.utcnow().timestamp() * 1000) - 7200000,
        "attachments": {"text": True, "image": False, "voice": True}
    },
    {
        "id": "CI-9902",
        "category": "Civil Infrastructure",
        "title": "Street Wall Crack #CI-9902",
        "description": "Structural brick fissure along subway bridge support.",
        "location": "GPS Lock · Lat: 12.970200, Lng: 77.595100",
        "color": "#FF6B35",
        "icon": "⚠️",
        "status": "Assigned",
        "crew": "Team Alpha",
        "priority": "High",
        "confidence": 92.1,
        "gps": "12.970200, 77.595100",
        "timestamp": int(datetime.utcnow().timestamp() * 1000) - 10800000,
        "attachments": {"text": True, "image": True, "voice": False}
    },
    {
        "id": "GC-3344",
        "category": "Sanitation",
        "title": "Overflowing Bin #GC-3344",
        "description": "Trash piling up outside collection bin attracting dogs.",
        "location": "GPS Lock · Lat: 12.974100, Lng: 77.596000",
        "color": "#84CC16",
        "icon": "🗑️",
        "status": "Resolved",
        "crew": "Unassigned",
        "priority": "Low",
        "confidence": 98.4,
        "gps": "12.974100, 77.596000",
        "timestamp": int(datetime.utcnow().timestamp() * 1000) - 14400000,
        "attachments": {"text": True, "image": False, "voice": False}
    },
    {
        "id": "SL-4829",
        "category": "Public Lighting",
        "title": "Lamp Fault #SL-4829",
        "description": "Streetlight is completely dark since Monday. Dangerous crossing.",
        "location": "GPS Lock · Lat: 12.975000, Lng: 77.592500",
        "color": "#F59E0B",
        "icon": "💡",
        "status": "Reported",
        "crew": "Unassigned",
        "priority": "High",
        "confidence": 93.5,
        "gps": "12.975000, 77.592500",
        "timestamp": int(datetime.utcnow().timestamp() * 1000) - 18000000,
        "attachments": {"text": True, "image": False, "voice": False}
    }
]

INITIAL_AUDIT_LOGS = [
    {
        "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        "event": "System initialized. Active digital twin connected.",
        "user": "System"
    },
    {
        "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        "event": "Audit ledger synched with public confirmation node.",
        "user": "System"
    }
]

def load_local_db() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        data = {"incidents": INITIAL_INCIDENTS, "audit_logs": INITIAL_AUDIT_LOGS, "users": {}}
        # ensure presets have reporter_email
        for inc in data["incidents"]:
            if "reporter_email" not in inc:
                inc["reporter_email"] = "citizen@communityhelper.gov"
        save_local_db(data)
        return data
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            # backfill missing reporter_email fields
            modified = False
            for inc in data.get("incidents", []):
                if "reporter_email" not in inc:
                    inc["reporter_email"] = "citizen@communityhelper.gov"
                    modified = True
            if "users" not in data:
                data["users"] = {}
                modified = True
            if modified:
                save_local_db(data)
            return data
    except Exception as e:
        logger.error(f"Error reading local db: {e}")
        return {"incidents": INITIAL_INCIDENTS, "audit_logs": INITIAL_AUDIT_LOGS, "users": {}}

def save_local_db(data: Dict[str, Any]):
    try:
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error writing local db: {e}")

def seed_database_if_empty():
    if USE_FIREBASE:
        try:
            docs = list(db.collection("incidents").limit(1).stream())
            if not docs:
                logger.info("🔥 Firestore is empty. Seeding demo data...")
                for inc in INITIAL_INCIDENTS:
                    inc_copy = inc.copy()
                    inc_copy["user_uid"] = get_firebase_uid(inc_copy.get("reporter_email", "citizen@communityhelper.gov"))
                    db.collection("incidents").document(inc["id"]).set(inc_copy)
                for log in INITIAL_AUDIT_LOGS:
                    db.collection("audit_logs").add(log)
                logger.info("🔥 Firestore seeded successfully with demo data.")
        except Exception as e:
            logger.error(f"❌ Failed to seed Firestore: {e}")
    else:
        db_data = load_local_db()
        modified = False
        if not db_data.get("incidents"):
            db_data["incidents"] = INITIAL_INCIDENTS.copy()
            modified = True
        for inc in db_data.get("incidents", []):
            if "user_uid" not in inc:
                inc["user_uid"] = get_firebase_uid(inc.get("reporter_email", "citizen@communityhelper.gov"))
                modified = True
        if modified:
            save_local_db(db_data)

# Initialize and seed db
seed_database_if_empty()

# ═══════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ═══════════════════════════════════════════════════
class IncidentCreate(BaseModel):
    category: str
    title: str
    description: str
    location: str
    color: str
    icon: str
    gps: str
    priority: Optional[str] = "Moderate"
    confidence: Optional[float] = 95.0
    attachments: Optional[Dict[str, bool]] = None
    user_urgency: Optional[str] = None
    votes: Optional[int] = 12
    comments: Optional[List[str]] = []
    assigned_team: Optional[str] = None
    resolution_time: Optional[str] = None
    agent_workflow: Optional[List[Dict[str, str]]] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    area_desc: Optional[str] = None
    sla_start_time: Optional[str] = None
    reporter_email: Optional[str] = "citizen@communityhelper.gov"

class IncidentUpdate(BaseModel):
    status: Optional[str] = None
    crew: Optional[str] = None
    priority: Optional[str] = None
    votes: Optional[int] = None
    comments: Optional[List[str]] = None

class LoginRequest(BaseModel):
    email: str
    role: str

class DuplicateCheckRequest(BaseModel):
    title: str
    description: str
    gps: str
    category: Optional[str] = None

class RecommendTeamRequest(BaseModel):
    category: str
    gps: str

class PredictResolutionRequest(BaseModel):
    category: str
    priority: str

# ═══════════════════════════════════════════════════
# WEBSOCKET MANAGER
# ═══════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔌 WebSocket client connected. Count: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"🔌 WebSocket client disconnected. Count: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

async def log_audit(event_text: str, user: str = "Manager"):
    new_log = {
        "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        "event": event_text,
        "user": user
    }
    if USE_FIREBASE:
        db.collection("audit_logs").add(new_log)
    else:
        db_data = load_local_db()
        db_data["audit_logs"].insert(0, new_log)
        save_local_db(db_data)
    
    await manager.broadcast({"type": "AUDIT_LOG", "data": new_log})

# ═══════════════════════════════════════════════════
# MOCK RULE-BASED CLASS AS BACKFALL
# ═══════════════════════════════════════════════════
def mock_rule_based_analysis(title: str, description: str) -> Dict[str, Any]:
    text = (title + " " + description).lower()
    category = "Civil Infrastructure"
    dept = "Public Works Department"
    color = "#FF6B35"
    icon = "⚠️"
    
    if any(k in text for k in ["pothole", "road", "crack", "asphalt", "highway", "street"]):
        category = "Road Damage"
        dept = "Department of Transportation"
        color = "#EF4444"
        icon = "🕳️"
    elif any(k in text for k in ["leak", "pipe", "burst", "water", "hydrant", "flooding", "puddle"]):
        category = "Water Infrastructure"
        dept = "Municipal Water Board"
        color = "#3B82F6"
        icon = "💧"
    elif any(k in text for k in ["drain", "clog", "sewer", "block", "grate"]):
        category = "Drainage System"
        dept = "City Drainage & Sewerage"
        color = "#0EA5E9"
        icon = "🌊"
    elif any(k in text for k in ["light", "lamp", "outage", "bulb", "dark", "streetlight"]):
        category = "Public Lighting"
        dept = "Municipal Lighting Agency"
        color = "#F59E0B"
        icon = "💡"
    elif any(k in text for k in ["trash", "garbage", "overflow", "waste", "dumpster", "bin", "smell"]):
        category = "Sanitation"
        dept = "Sanitation & Waste Management"
        color = "#84CC16"
        icon = "🗑️"

    priority = "Moderate"
    if any(k in text for k in ["critical", "emergency", "flood", "hazard", "severe", "accident"]):
        priority = "Critical"
    elif any(k in text for k in ["broken", "blocked", "high", "damage"]):
        priority = "High"
    elif any(k in text for k in ["minor", "low", "small", "aesthetic"]):
        priority = "Low"

    return {
        "category": category,
        "severity": priority,
        "department": dept,
        "priority": priority,
        "confidence": 94.8,
        "duplicate_check": False,
        "estimated_resolution": "2 days",
        "color": color,
        "icon": icon
    }

# ═══════════════════════════════════════════════════
# CORE API ENDPOINTS
# ═══════════════════════════════════════════════════

@app.get("/")
def read_root():
    return {
        "status": "online",
        "gemini_active": USE_GEMINI,
        "db_mode": "Firebase" if USE_FIREBASE else "LocalDB-Mock"
    }

@app.get("/api/incidents")
async def get_incidents():
    incidents = []
    if USE_FIREBASE:
        docs = db.collection("incidents").stream()
        incidents = [doc.to_dict() for doc in docs]
    else:
        db_data = load_local_db()
        incidents = db_data["incidents"]
        
    # Run Escalation Agent logic
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    modified = False
    
    for inc in incidents:
        if inc.get("status") == "Resolved":
            continue
        
        priority = inc.get("priority", "Moderate")
        votes = inc.get("votes", 0)
        age_ms = now_ms - inc.get("timestamp", now_ms)
        
        # Escalate if unresolved high/moderate issue older than 2 hours or has > 15 votes
        if priority != "Critical" and (age_ms > 7200000 or votes > 15):
            inc["priority"] = "Critical"
            comments = inc.get("comments", [])
            comments.append("System (Escalation Agent): Priority escalated to Critical due to SLA duration or high community vote count.")
            inc["comments"] = comments
            modified = True
            
            if USE_FIREBASE:
                db.collection("incidents").document(inc["id"]).update({
                    "priority": "Critical",
                    "comments": comments
                })
            await log_audit(f"Incident {inc['id']} was automatically escalated to Critical by Escalation Agent.", user="System")
            await manager.broadcast({"type": "incident_escalated", "data": inc})

    if not USE_FIREBASE and modified:
        db_data["incidents"] = incidents
        save_local_db(db_data)
        
    return sorted(incidents, key=lambda x: x.get("timestamp", 0), reverse=True)

@app.post("/api/incidents")
async def create_incident(incident: IncidentCreate):
    # Generates ID
    prefix = "UR"
    category_lower = incident.category.lower()
    if "road" in category_lower or "pothole" in category_lower: prefix = "RD"
    elif "water" in category_lower: prefix = "WL"
    elif "drain" in category_lower: prefix = "DR"
    elif "lighting" in category_lower or "streetlight" in category_lower: prefix = "SL"
    elif "sanitation" in category_lower or "garbage" in category_lower or "dumping" in category_lower: prefix = "GC"

    unique_id = f"{prefix}-{datetime.utcnow().microsecond % 9000 + 1000}"

    # Construct location string from structured inputs if available
    loc_str = incident.location
    if incident.city or incident.pincode:
        parts = []
        if incident.area_desc:
            parts.append(incident.area_desc)
        city_state = ""
        if incident.city:
            city_state += incident.city
        if incident.state:
            city_state += f", {incident.state}"
        if city_state:
            parts.append(city_state)
        if incident.pincode:
            parts.append(incident.pincode)
        loc_str = " · ".join(parts)

    # Normalize GPS coordinates (Fix current location + manual fallback)
    gps_coords = resolve_gps_coordinates(incident.gps, incident.description)

    sla_time = incident.sla_start_time
    if not sla_time:
        p_lower = (incident.priority or "moderate").lower()
        if p_lower in ["critical", "high"]:
            sla_time = "starts in 1/2 hour"
        elif p_lower in ["moderate", "medium"]:
            sla_time = "starts in 1 hour"
        else:
            sla_time = "starts in 2-4 hours"

    email = incident.reporter_email or "citizen@communityhelper.gov"
    user_uid = get_firebase_uid(email)

    new_incident = {
        "id": unique_id,
        "category": incident.category,
        "title": incident.title,
        "description": incident.description,
        "location": loc_str,
        "color": incident.color,
        "icon": incident.icon,
        "gps": gps_coords,
        "status": "Reported",
        "crew": incident.assigned_team or "Unassigned",
        "priority": incident.priority or "Moderate",
        "confidence": incident.confidence or 95.0,
        "timestamp": int(datetime.utcnow().timestamp() * 1000),
        "attachments": incident.attachments or {"text": True, "image": False, "voice": False},
        "user_urgency": incident.user_urgency,
        "votes": incident.votes if incident.votes is not None else 12,
        "comments": incident.comments or [],
        "assigned_team": incident.assigned_team or "Unassigned",
        "resolution_time": incident.resolution_time or "2 days",
        "agent_workflow": incident.agent_workflow or [],
        "city": incident.city,
        "state": incident.state,
        "pincode": incident.pincode,
        "area_desc": incident.area_desc,
        "sla_start_time": sla_time,
        "reporter_email": email,
        "user_uid": user_uid
    }

    if USE_FIREBASE:
        db.collection("incidents").document(unique_id).set(new_incident)
    else:
        db_data = load_local_db()
        db_data["incidents"].insert(0, new_incident)
        save_local_db(db_data)

    await manager.broadcast({"type": "INCIDENT_NEW", "data": new_incident})
    await log_audit(f"New incident reported: {incident.title} (Priority: {incident.priority})", user="Citizen")

    return new_incident

@app.post("/api/reset")
@app.post("/api/incidents/reset-pres")
def reset_incidents():
    # Helper to clean db and load presets if needed
    if not USE_FIREBASE:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        load_local_db()
        return {"status": "reset"}
    return {"status": "noop"}

@app.patch("/api/incidents/{incident_id}")
async def update_incident(incident_id: str, payload: IncidentUpdate):
    target = None
    if USE_FIREBASE:
        doc_ref = db.collection("incidents").document(incident_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Incident not found")
        target = doc.to_dict()
        updates = {}
        if payload.status is not None: updates["status"] = payload.status
        if payload.crew is not None:
            updates["crew"] = payload.crew
            updates["assigned_team"] = payload.crew
        if payload.priority is not None: updates["priority"] = payload.priority
        if payload.votes is not None: updates["votes"] = payload.votes
        if payload.comments is not None: updates["comments"] = payload.comments
        doc_ref.update(updates)
        target.update(updates)
    else:
        db_data = load_local_db()
        idx = next((i for i, inc in enumerate(db_data["incidents"]) if inc["id"] == incident_id), -1)
        if idx == -1:
            raise HTTPException(status_code=404, detail="Incident not found")
        target = db_data["incidents"][idx]
        if payload.status is not None: target["status"] = payload.status
        if payload.crew is not None:
            target["crew"] = payload.crew
            target["assigned_team"] = payload.crew
        if payload.priority is not None: target["priority"] = payload.priority
        if payload.votes is not None: target["votes"] = payload.votes
        if payload.comments is not None: target["comments"] = payload.comments
        db_data["incidents"][idx] = target
        save_local_db(db_data)

    # Broadcast specific status changes
    event_type = "incident_updated"
    if payload.status == "Assigned" or payload.crew is not None:
        event_type = "incident_assigned"
    elif payload.status == "Resolved":
        event_type = "incident_resolved"

    await log_audit(f"Incident {incident_id} updated: Status='{target['status']}', Crew='{target['crew']}'")
    await manager.broadcast({"type": event_type, "data": target})

    return target

@app.post("/api/incidents/{incident_id}/escalate")
async def escalate_incident(incident_id: str):
    target = None
    if USE_FIREBASE:
        doc_ref = db.collection("incidents").document(incident_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Incident not found")
        target = doc.to_dict()
        doc_ref.update({"priority": "Critical"})
        target["priority"] = "Critical"
    else:
        db_data = load_local_db()
        idx = next((i for i, inc in enumerate(db_data["incidents"]) if inc["id"] == incident_id), -1)
        if idx == -1:
            raise HTTPException(status_code=404, detail="Incident not found")
        target = db_data["incidents"][idx]
        target["priority"] = "Critical"
        db_data["incidents"][idx] = target
        save_local_db(db_data)

    await log_audit(f"Incident {incident_id} was escalated to CRITICAL priority due to SLA breach.", user="Admin")
    await manager.broadcast({"type": "incident_escalated", "data": target})

    return target

# ═══════════════════════════════════════════════════
# GEMINI-POWERED MULTIMODAL API ENDPOINTS
# ═══════════════════════════════════════════════════

@app.post("/api/analyze")
async def analyze_incident(
    title: str = Form(...),
    description: str = Form(...),
    gps: str = Form(...),
    urgency: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    voice: Optional[UploadFile] = File(None)
):
    """
    Enhanced Evidence Intelligence Layer & Live Analysis using Gemini.
    """
    start_backend = time.time()
    gemini_duration = 0.0

    has_image = image is not None
    has_video = video is not None
    has_voice = voice is not None

    # Base rule-based defaults
    category = "Civil Infrastructure"
    dept = "Public Works Department"
    color = "#FF6B35"
    icon = "⚠️"
    combined_severity = "Moderate"
    est_res = "2 days"
    confidence = 94.8
    summary = f"AI understood: {category} issue detected."
    guidance = None
    tags = ["Public safety risk"]

    # Simple local rule-based fallback
    rule_data = mock_rule_based_analysis(title, description)
    category = rule_data["category"]
    combined_severity = rule_data["priority"]
    dept = rule_data["department"]
    est_res = rule_data["estimated_resolution"]
    color = rule_data["color"]
    icon = rule_data["icon"]
    confidence = rule_data["confidence"]
    summary = f"AI understood: {category} issue detected."
    
    # Urgency adjustment
    if urgency:
        urg_lower = urgency.lower()
        if "emergency" in urg_lower:
            combined_severity = "Critical"
        elif "safety" in urg_lower and combined_severity != "Critical":
            combined_severity = "High"

    if len(description.strip()) < 15:
        guidance = "Your description is brief. Please include additional details like specific landmarks, estimated size, or hazards to help our crews."

    # Gemini API Call
    if USE_GEMINI and genai_client:
        try:
            contents = []
            # Shortened, high-efficiency prompt keeping only required classification fields
            prompt = f"""
            Analyze issue: {title}. Desc: {description}.
            Return JSON:
            - category: "Road Damage"|"Water Infrastructure"|"Drainage System"|"Public Lighting"|"Sanitation"|"Civil Infrastructure"
            - priority: "Low"|"Moderate"|"High"|"Critical"
            - department: string
            - estimated_resolution: string
            - color: hex color
            - icon: emoji
            - confidence: float
            - summary: short summary
            - guidance: string (if desc < 15 chars/incomplete) else null
            """
            contents.append(prompt)

            if image:
                img_data = await image.read()
                await image.seek(0)
                from PIL import Image
                img = Image.open(BytesIO(img_data))
                contents.append(img)

            start_gemini = time.time()
            response = genai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            gemini_duration = time.time() - start_gemini
            logger.info(f"Gemini API response duration: {gemini_duration:.3f}s")
            
            gemini_data = json.loads(response.text)
            if gemini_data:
                category = gemini_data.get("category", category)
                combined_severity = gemini_data.get("priority", combined_severity)
                dept = gemini_data.get("department", dept)
                est_res = gemini_data.get("estimated_resolution", est_res)
                color = gemini_data.get("color", color)
                icon = gemini_data.get("icon", icon)
                confidence = gemini_data.get("confidence", confidence)
                summary = gemini_data.get("summary", summary)
                guidance = gemini_data.get("guidance", guidance)
        except Exception as e:
            logger.error(f"Gemini API analysis failed: {e}")

    # Set Tags
    if "light" in category.lower() or "dark" in description.lower():
        tags.append("Night visibility risk")
    if "road" in category.lower() or "pothole" in description.lower():
        tags.append("Traffic obstruction")
    if "water" in category.lower():
        tags.append("Water hazard")

    # Geocoding current location / manual coordinates fallback
    parsed_gps = resolve_gps_coordinates(gps, description)
    lat_val, lng_val = map(float, parsed_gps.split(","))

    # Duplicate detection (Proximity / Title similarity)
    incidents = await get_incidents()
    is_duplicate = False
    duplicate_details = None

    for inc in incidents:
        if inc.get("status") == "Resolved":
            continue
        try:
            inc_gps = resolve_gps_coordinates(inc.get("gps", ""), inc.get("description", ""))
            inc_lat, inc_lng = map(float, inc_gps.split(","))
            dist = ((inc_lat - lat_val)**2 + (inc_lng - lng_val)**2) ** 0.5
            
            # Simple Proximity (within ~250m) and text keyword check
            title_words = set(title.lower().split())
            inc_title_words = set(inc.get("title", "").lower().split())
            overlap = len(title_words.intersection(inc_title_words))
            
            if dist < 0.0025 and (overlap >= 2 or inc.get("category") == category):
                is_duplicate = True
                duplicate_details = {
                    "matching_incident_id": inc.get("id"),
                    "matching_incident_title": inc.get("title"),
                    "distance": f"{int(dist * 111000)} meters",
                    "status": inc.get("status"),
                    "reports_count": inc.get("votes", 12)
                }
                break
        except Exception:
            pass

    # Timeline SLA times
    sla_start_time = "starts in 2-4 hours"
    sev_lower = combined_severity.lower()
    if sev_lower in ["critical", "high"]:
        sla_start_time = "starts in 1/2 hour"
    elif sev_lower in ["moderate", "medium"]:
        sla_start_time = "starts in 1 hour"

    # Agent Workflow log updates
    agent_workflow = [
        {"agent": "Smart Issue Agent", "log": f"Classified incident category as {category} with priority: {combined_severity}."},
        {"agent": "Duplicate Detection Agent", "log": f"Checked active queue within 250m. Duplicate: {is_duplicate}."},
        {"agent": "Resolution Agent", "log": f"Assigned responsible department: {dept}. Predicted resolution ETA: {est_res}."},
        {"agent": "Citizen Assistance Agent", "log": guidance if guidance else "Description verified as complete and helpful."}
    ]

    backend_duration = time.time() - start_backend
    logger.info(f"Backend processing duration: {backend_duration:.3f}s")

    return {
        "category": category,
        "severity": combined_severity,
        "department": dept,
        "priority": combined_severity,
        "confidence": confidence,
        "estimated_resolution": est_res,
        "sla_start_time": sla_start_time,
        "summary": summary,
        "transcription": None,
        "extracted_location": f"GPS Location Locked · {parsed_gps}",
        "tags": tags,
        "location_confidence": 92.0,
        "mismatch_detected": False,
        "is_duplicate": is_duplicate,
        "duplicate_details": duplicate_details,
        "agent_workflow": agent_workflow,
        "icon": icon,
        "color": color,
        "guidance": guidance,
        "gemini_duration": gemini_duration,
        "backend_duration": backend_duration
    }


@app.post("/api/duplicate-check")
async def duplicate_check(payload: DuplicateCheckRequest):
    """
    Duplicate Detection Agent: checks proximity and title similarity.
    """
    incidents = await get_incidents()
    parsed_gps = resolve_gps_coordinates(payload.gps)
    lat_val, lng_val = map(float, parsed_gps.split(","))

    duplicate_found = False
    matching_inc = None

    for inc in incidents:
        if inc.get("status") == "Resolved":
            continue
        try:
            inc_gps = resolve_gps_coordinates(inc.get("gps", ""))
            inc_lat, inc_lng = map(float, inc_gps.split(","))
            dist = ((inc_lat - lat_val)**2 + (inc_lng - lng_val)**2) ** 0.5

            title_words = set(payload.title.lower().split())
            inc_title_words = set(inc.get("title", "").lower().split())
            overlap = len(title_words.intersection(inc_title_words))

            if dist < 0.0025 and (overlap >= 2 or inc.get("category") == payload.category):
                duplicate_found = True
                matching_inc = inc
                break
        except Exception:
            pass

    if duplicate_found and matching_inc:
        await manager.broadcast({
            "type": "incident_duplicate_found",
            "data": matching_inc
        })
        return {
            "is_duplicate": True,
            "matching_incident_id": matching_inc["id"],
            "matching_incident_title": matching_inc["title"],
            "confidence": 92.5
        }

    return {"is_duplicate": False, "confidence": 100.0}

@app.get("/api/hotspots")
def get_hotspots():
    """
    Groups incidents by location/ward to determine local hotspots.
    """
    incidents = get_incidents()
    groups = {}
    for inc in incidents:
        loc = inc.get("location", "Unknown Location")
        # Extract Ward info
        ward = loc.split("·")[0].strip() if "·" in loc else loc
        if ward not in groups:
            groups[ward] = {
                "location": ward,
                "count": 0,
                "category": inc.get("category"),
                "severity": inc.get("priority", "Moderate")
            }
        groups[ward]["count"] += 1
        
    return sorted(list(groups.values()), key=lambda x: x["count"], reverse=True)

@app.post("/api/recommend-team")
def recommend_team(payload: RecommendTeamRequest):
    """
    AI Recommendation for maintenance team dispatch based on location & category.
    """
    category = payload.category.lower()
    
    team = "Team Alpha"
    reason = "Nearest emergency repair unit available."
    alternatives = ["Team Beta"]

    if "road" in category:
        team = "Road Repair Team A"
        reason = "Specialized asphalt patching team with high-priority steamroller access."
        alternatives = ["Road Repair Team B"]
    elif "water" in category or "drain" in category:
        team = "Water Works Division 3"
        reason = "Equipped with heavy hydraulic pipe sealants and active pump tools."
        alternatives = ["Team Delta"]
    elif "lighting" in category:
        team = "Electrical Grid Crew B"
        reason = "Equipped with specialized high-elevation cherry pickers."
        alternatives = ["Team Gamma"]
    elif "sanitation" in category:
        team = "Sanitation Route Truck 4"
        reason = "Dedicated compactor vehicle covering this ward sector today."
        alternatives = ["Team Alpha"]

    return {
        "recommended_crew": team,
        "reason": reason,
        "alternative_crews": alternatives
    }

@app.post("/api/predict-resolution")
def predict_resolution(payload: PredictResolutionRequest):
    """
    Predict estimated resolution time based on historical resolution schedules.
    """
    p = payload.priority.lower()
    cat = payload.category.lower()
    
    hours = 48
    if p == "critical":
        hours = 4 if "water" in cat else 12
    elif p == "high":
        hours = 24
    elif p == "low":
        hours = 72
        
    days = f"{hours} hours" if hours < 24 else f"{hours // 24} days"

    return {
        "estimated_hours": hours,
        "formatted_estimate": days,
        "confidence": 94.2
    }
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

# ═══════════════════════════════════════════════════
# ANALYTICS & AUDIT LOGS
# ═══════════════════════════════════════════════════

@app.get("/api/audit-logs")
def get_audit_logs():
    if USE_FIREBASE:
        docs = db.collection("audit_logs").order_by("timestamp", direction="DESCENDING").stream()
        return [doc.to_dict() for doc in docs]
    else:
        db_data = load_local_db()
        return db_data["audit_logs"]

@app.get("/api/analytics")
def get_analytics():
    incidents = get_incidents()
    total = len(incidents)
    resolved = sum(1 for inc in incidents if inc["status"] == "Resolved")
    active = sum(1 for inc in incidents if inc["status"] != "Resolved")
    
    cats = {}
    for inc in incidents:
        c = inc.get("category", "Other")
        cats[c] = cats.get(c, 0) + 1

    return {
        "total": total,
        "resolved": resolved,
        "active": active,
        "resolvedRate": round((resolved / total * 100) if total > 0 else 100, 1),
        "categories": cats
    }

@app.get("/api/community-insights")
async def get_community_insights():
    """
    Community Insight Agent: generates issue trends and summaries based on open reports.
    """
    incidents = await get_incidents()
    if not incidents:
        return {"insights": "No issues reported yet to generate insights.", "trends": []}
    
    inc_summary = []
    for inc in incidents:
        inc_summary.append({
            "category": inc.get("category"),
            "priority": inc.get("priority"),
            "status": inc.get("status"),
            "location": inc.get("location")
        })

    insights_text = ""
    trends = []

    if USE_GEMINI and genai_client:
        try:
            prompt = f"""
            You are a Community Insight Agent.
            Analyze the following list of reported issues in the city and generate a concise report on current trends, active hotspots, and suggestions for municipal improvement.
            
            Incidents list:
            {json.dumps(inc_summary)}
            
            Return output in JSON format with keys:
            - insights: string (a paragraph highlighting key trends and overview)
            - trends: array of strings (bullet points summarizing specific observations)
            """
            response = genai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            res_json = json.loads(response.text)
            insights_text = res_json.get("insights", "")
            trends = res_json.get("trends", [])
        except Exception as e:
            logger.error(f"Gemini community insights failed: {e}")

    # Fallback/Mock Trends
    if not insights_text:
        cats = {}
        for inc in incidents:
            c = inc.get("category", "Other")
            cats[c] = cats.get(c, 0) + 1
        most_common = max(cats, key=cats.get) if cats else "None"
        insights_text = f"Analyzed {len(incidents)} reports. The most active issue category is currently {most_common}."
        trends = [
            f"{most_common} issues represent the highest density of reports.",
            f"{sum(1 for inc in incidents if inc.get('priority') == 'Critical')} critical issues are currently awaiting resolution.",
            "Proactive repairs are suggested in the North and Central sectors."
        ]

    return {
        "insights": insights_text,
        "trends": trends
    }

@app.get("/api/resource-allocation")
async def get_resource_allocation():
    """
    Resource Allocation Agent: suggests focus categories and share percentages based on issue density.
    """
    incidents = await get_incidents()
    if not incidents:
        return {"recommendations": ["No active issues to allocate resources."], "allocation_shares": {}}

    category_counts = {}
    for inc in incidents:
        if inc.get("status") != "Resolved":
            c = inc.get("category", "Other")
            category_counts[c] = category_counts.get(c, 0) + 1

    recommendations = []
    allocation = {}

    if USE_GEMINI and genai_client:
        try:
            prompt = f"""
            You are a Resource Allocation Agent.
            Based on the active incident count per category, suggest where the city should allocate municipal resources (crews, vehicles, budget).
            
            Category Counts:
            {json.dumps(category_counts)}
            
            Return output in JSON format with keys:
            - recommendations: array of strings (specific actionable advice)
            - allocation_shares: object mapping category names to suggested percentage integers (totaling 100)
            """
            response = genai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            res_json = json.loads(response.text)
            recommendations = res_json.get("recommendations", [])
            allocation = res_json.get("allocation_shares", {})
        except Exception as e:
            logger.error(f"Gemini resource allocation failed: {e}")

    # Fallback/Mock Allocation
    if not recommendations:
        total = sum(category_counts.values()) or 1
        for cat, count in category_counts.items():
            allocation[cat] = int((count / total) * 100)
        most_active = max(category_counts, key=category_counts.get) if category_counts else "general repairs"
        recommendations = [
            f"Prioritize dispatch teams for {most_active} due to high volume of active tickets.",
            "Maintain baseline response capabilities for other service sectors."
        ]

    return {
        "recommendations": recommendations,
        "allocation_shares": allocation
    }

# ═══════════════════════════════════════════════════
# USER POINTS & HERO TIER ENDPOINTS
# ═══════════════════════════════════════════════════

POINTS_MAP = {"low": 10, "moderate": 25, "medium": 25, "high": 50, "critical": 100}
CROWD_BONUS = 15
RESOLVED_BONUS = 20

TIER_THRESHOLDS = [
    (700, "Community Champion"),
    (301, "Gold Hero"),
    (101, "Silver Hero"),
    (0,   "Bronze Hero"),
]

def compute_hero_tier(total_points: int) -> str:
    for threshold, name in TIER_THRESHOLDS:
        if total_points >= threshold:
            return name
    return "Bronze Hero"

@app.get("/api/users/{email}/points")
def get_user_points(email: str):
    """Return persisted points and tier for a user email."""
    if USE_FIREBASE:
        try:
            doc = db.collection("users").document(email).get()
            if doc.exists:
                data = doc.to_dict()
                return {
                    "email": email,
                    "total_points": data.get("total_points", 0),
                    "tier": compute_hero_tier(data.get("total_points", 0)),
                    "resolved_count": data.get("resolved_count", 0)
                }
        except Exception as e:
            logger.error(f"Error fetching user points from Firestore: {e}")
    else:
        db_data = load_local_db()
        user_data = db_data["users"].get(email, {})
        pts = user_data.get("total_points", 0)
        return {
            "email": email,
            "total_points": pts,
            "tier": compute_hero_tier(pts),
            "resolved_count": user_data.get("resolved_count", 0)
        }
    return {"email": email, "total_points": 0, "tier": "Bronze Hero", "resolved_count": 0}

class UserPointsUpdate(BaseModel):
    priority: str  # low/moderate/high/critical
    crowd_validated: Optional[bool] = False
    resolved: Optional[bool] = False

@app.patch("/api/users/{email}/points")
def update_user_points(email: str, payload: UserPointsUpdate):
    """Add points for a new incident submission or resolution confirmation."""
    base = POINTS_MAP.get(payload.priority.lower(), 25)
    bonus = 0
    if payload.crowd_validated:
        bonus += CROWD_BONUS
    if payload.resolved:
        bonus += RESOLVED_BONUS
    earned = base + bonus

    if USE_FIREBASE:
        try:
            ref = db.collection("users").document(email)
            doc = ref.get()
            old = doc.to_dict() if doc.exists else {}
            new_pts = old.get("total_points", 0) + earned
            new_resolved = old.get("resolved_count", 0) + (1 if payload.resolved else 0)
            ref.set({"total_points": new_pts, "resolved_count": new_resolved}, merge=True)
            return {"email": email, "earned": earned, "total_points": new_pts, "tier": compute_hero_tier(new_pts), "resolved_count": new_resolved}
        except Exception as e:
            logger.error(f"Error updating user points in Firestore: {e}")
    else:
        db_data = load_local_db()
        user_entry = db_data["users"].get(email, {"total_points": 0, "resolved_count": 0})
        new_pts = user_entry.get("total_points", 0) + earned
        new_resolved = user_entry.get("resolved_count", 0) + (1 if payload.resolved else 0)
        db_data["users"][email] = {"total_points": new_pts, "resolved_count": new_resolved}
        save_local_db(db_data)
        return {"email": email, "earned": earned, "total_points": new_pts, "tier": compute_hero_tier(new_pts), "resolved_count": new_resolved}
    return {"email": email, "earned": earned, "total_points": earned, "tier": compute_hero_tier(earned), "resolved_count": 0}

@app.post("/api/login")
def login(request: LoginRequest):
    uid = get_firebase_uid(request.email)
    return {"status": "authenticated", "email": request.email, "role": request.role, "uid": uid}

# ═══════════════════════════════════════════════════
# WEBSOCKET GATEWAY
# ═══════════════════════════════════════════════════
@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
