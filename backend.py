"""
AgentWatch — Real AI Agent Monitor (Groq Cloud Version)
=========================================================
Groq runs Llama 3 in the cloud — fast, free, no laptop needed.
Deploy this on Render.com for a live public demo link.

Set environment variable on Render:
  GROQ_API_KEY = your_groq_key_here
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn
import time
import os
import re
import json

# ── Groq Client ───────────────────────────────────────────────────────
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama3-8b-8192"  # Fast, free Groq model

app = FastAPI(title="AgentWatch", version="5.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Serve frontend static files
if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")

# ── Stats ─────────────────────────────────────────────────────────────
stats = {"total": 0, "blocked": 0, "allowed": 0, "flagged": 0}
history = []
feedback_count = 0
correct_flags = 0
pending_reviews = {}

# ── NLP Risk Patterns ─────────────────────────────────────────────────
CRITICAL_PATTERNS = [
    (r'\b(delete|drop|remove|truncate|wipe|erase|destroy)\b.{0,40}(all|every|bulk|entire|database|table|record|user|customer|account|file|data)',
     "Bulk destructive operation — affects all records"),
    (r'\b(bulk|mass|batch)\b.{0,25}(delete|remove|update|modify|send|notify|freeze|block)',
     "Mass operation without individual review"),
    (r'\b(bypass|skip|ignore|override)\b.{0,25}(auth|check|verify|validation|approval|review|permission|security)',
     "Safety check bypass detected"),
    (r'\b(permanent|irreversible|cannot.{0,5}undo|no.{0,5}backup|unrecoverable)\b',
     "Irreversible action — cannot be undone"),
    (r'\ball\s+(users?|accounts?|customers?|clients?|records?|files?|data|employees?)\b',
     "Action targets ALL entities with no filtering"),
    (r'\b(production|prod\b).{0,30}(delete|drop|modify|update|wipe|truncate)',
     "Destructive action on production environment"),
    (r'\bno\s+(review|approval|check|verification|human|manual)\b',
     "No human review in planned actions"),
    (r'\b(assume|probably|likely|should\s+be\s+fine|typically)\b.{0,60}(delete|remove|drop|wipe|clear|destroy)',
     "Assumption-based destructive action"),
    (r'\bsend.{0,35}(all|every|bulk|mass).{0,35}(email|message|notification|sms|alert)',
     "Bulk messaging without consent checks"),
    (r'\b(export|download|exfiltrate|extract).{0,30}(private|sensitive|personal|confidential|password|credential|secret)',
     "Sensitive data exfiltration detected"),
    (r'\bauto.{0,10}(approv|accept|confirm|execut|process).{0,30}(all|every|bulk|claim|request|transaction)',
     "Automated approval without review"),
    (r'\bfreeze.{0,20}(all|every|bulk).{0,20}(account|user|customer)',
     "Mass account freeze without assessment"),
    (r'\bdrop\s+(table|database|schema|index)', "Database structure deletion"),
    (r'\brm\s+-rf|rmdir\s+/s|del\s+/[sf]', "Force delete command detected"),
]

HIGH_PATTERNS = [
    (r'\bdelete\b', "Delete operation present"),
    (r'\boverwrite\b', "Overwrite operation present"),
    (r'\bno\s+backup\b', "No backup mentioned"),
    (r'\b(admin|root|sudo)\s+(access|privilege|permission)', "Elevated privilege usage"),
    (r'\b\d{3,}\s*(users?|accounts?|records?|files?|people|customers?)\b', "Large number of entities affected"),
    (r'\bwithout\s+(notif|inform|alert|telling)', "Action without notifying parties"),
    (r'\bimmediately\b.{0,30}(delete|remove|wipe|clear|drop)', "Immediate destructive action"),
]

ACTION_RISK = {
    "list_files": 0.0, "read_file": 0.05, "search_in_files": 0.05,
    "create_file": 0.1, "append_to_file": 0.2, "copy_file": 0.15,
    "overwrite_file": 0.5, "delete_file": 0.65, "delete_all_files": 0.95,
    "general": 0.2,
}

REVERSIBILITY_RISK = {
    "list_files": 0.0, "read_file": 0.0, "search_in_files": 0.0,
    "create_file": 0.0, "append_to_file": 0.2, "copy_file": 0.0,
    "overwrite_file": 0.8, "delete_file": 1.0, "delete_all_files": 1.0,
    "general": 0.3,
}


def analyze_risk(reasoning: str, planned: str, action_name: str) -> dict:
    full_text = (reasoning + " " + planned).lower()
    flags = []
    critical_count = 0
    high_count = 0

    for pattern, label in CRITICAL_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            flags.append({"severity": "critical", "message": label})
            critical_count += 1

    for pattern, label in HIGH_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            if not any(f["message"] == label for f in flags):
                flags.append({"severity": "high", "message": label})
                high_count += 1

    pattern_score = min(0.9, (critical_count * 0.3) + (high_count * 0.08))
    action_score = ACTION_RISK.get(action_name, 0.2)
    rev_score = REVERSIBILITY_RISK.get(action_name, 0.3)
    final_score = min(1.0, (pattern_score * 0.35) + (action_score * 0.45) + (rev_score * 0.20))

    if action_name in ["list_files", "search_in_files", "read_file", "copy_file"]:
        decision, risk_level = "ALLOW", "safe"
    elif action_name == "delete_all_files":
        decision, risk_level = "BLOCK", "critical"
    elif action_name == "overwrite_file":
        decision, risk_level = "BLOCK", "critical"
    elif action_name == "delete_file":
        decision, risk_level = "REVIEW", "high"
    elif final_score >= 0.70 or critical_count >= 2:
        decision, risk_level = "BLOCK", "critical"
    elif final_score >= 0.35 or high_count >= 2 or critical_count >= 1:
        decision, risk_level = "REVIEW", "high" if final_score >= 0.5 else "medium"
    elif final_score >= 0.15:
        decision, risk_level = "REVIEW", "medium"
    else:
        decision, risk_level = "ALLOW", "safe"

    return {
        "flags": flags, "risk_score": round(final_score, 2),
        "risk_level": risk_level, "decision": decision,
        "critical_count": critical_count, "high_count": high_count,
        "is_reversible": rev_score == 0.0,
    }


# ── Groq Agent ────────────────────────────────────────────────────────
AGENT_PROMPT = """You are an AI assistant. A user gave you a task.

Think carefully and respond in EXACTLY this format:

REASONING:
[Your step-by-step thinking about what this task requires and what you will do]

PLANNED ACTIONS:
[Numbered list of specific steps you will take]

CONCERNS:
[Any risks or concerns about this task]

RESPONSE:
[Your actual answer or output for this task]

Task: {task}"""


def call_groq(task: str) -> dict:
    client = Groq(api_key=GROQ_API_KEY)

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful AI assistant. Always respond in the exact format requested."},
            {"role": "user", "content": AGENT_PROMPT.format(task=task)}
        ],
        max_tokens=500,
        temperature=0.3,
    )

    raw = response.choices[0].message.content

    def extract(text, start, end):
        try:
            s = text.upper().find(start.upper())
            if s == -1: return ""
            s += len(start)
            if end:
                e = text.upper().find(end.upper(), s)
                return text[s:e].strip() if e != -1 else text[s:].strip()
            return text[s:].strip()
        except:
            return ""

    reasoning = extract(raw, "REASONING:", "PLANNED ACTIONS:") or raw[:300]
    actions = extract(raw, "PLANNED ACTIONS:", "CONCERNS:") or "Actions not specified"
    concerns = extract(raw, "CONCERNS:", "RESPONSE:") or "None identified"
    response_text = extract(raw, "RESPONSE:", None) or raw

    return {
        "reasoning": reasoning.strip(),
        "planned_actions": actions.strip(),
        "concerns": concerns.strip(),
        "response": response_text.strip(),
    }


def map_action(task: str) -> tuple:
    t = task.lower()
    if any(w in t for w in ["list", "show files", "what files", "directory"]):
        return "list_files", "List all files in workspace"
    elif any(w in t for w in ["delete all", "remove all", "wipe all", "clear all"]):
        return "delete_all_files", "DELETE ALL files — IRREVERSIBLE"
    elif any(w in t for w in ["delete", "remove", "wipe"]) and any(w in t for w in ["log", "file", ".csv", ".txt", ".json"]):
        return "delete_file", "Delete a specific file"
    elif any(w in t for w in ["read", "open", "show", "display", "contents"]):
        return "read_file", "Read file contents"
    elif any(w in t for w in ["search", "find", "look for", "contains"]):
        return "search_in_files", "Search through files"
    elif any(w in t for w in ["create", "make", "new file", "write a file"]):
        return "create_file", "Create a new file"
    elif any(w in t for w in ["overwrite", "replace content"]):
        return "overwrite_file", "Overwrite file content"
    elif any(w in t for w in ["freeze", "suspend", "block all", "disable all"]):
        return "delete_all_files", "Mass operation on all entities"
    elif any(w in t for w in ["send", "email", "message", "notify"]) and any(w in t for w in ["all", "every", "bulk", "mass"]):
        return "delete_all_files", "Bulk messaging operation"
    else:
        return "general", "General AI task"


def build_explanation(risk: dict, blocked: bool, action_desc: str) -> str:
    if blocked:
        top = [f["message"] for f in risk["flags"] if f["severity"] == "critical"]
        return (f"BLOCKED — AgentWatch intercepted this before execution. "
                f"Critical risks: {'; '.join(top[:2]) if top else 'high-risk operation'}. "
                f"Risk score: {int(risk['risk_score'] * 100)}%.")
    elif risk["decision"] == "REVIEW":
        return (f"FLAGGED FOR REVIEW — Risk score {int(risk['risk_score'] * 100)}%. "
                f"Action paused — your decision required.")
    else:
        return (f"ALLOWED — Risk score {int(risk['risk_score'] * 100)}%. "
                f"No dangerous patterns detected. Action approved.")


# ── API Endpoints ─────────────────────────────────────────────────────

@app.get("/")
def root():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return {"name": "AgentWatch", "status": "running", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok", "agent": "Groq Llama3", "model": GROQ_MODEL}

class TaskRequest(BaseModel):
    task: str

class FeedbackRequest(BaseModel):
    task_id: str
    was_correct: bool

class ApproveRequest(BaseModel):
    task_id: str

@app.post("/api/task")
def process_task(body: TaskRequest):
    if not body.task or len(body.task.strip()) < 3:
        return {"error": "Task too short"}

    task_id = f"task-{int(time.time())}"
    start = time.time()

    try:
        # Step 1 — Groq understands the task
        groq_result = call_groq(body.task)

        # Step 2 — Map to action type
        action_name, action_desc = map_action(body.task)

        # Step 3 — AgentWatch analyzes risk
        risk = analyze_risk(groq_result["reasoning"], groq_result["planned_actions"], action_name)

        decision = risk["decision"]
        blocked = decision == "BLOCK"
        elapsed = round(time.time() - start, 2)

        # Step 4 — Track stats
        stats["total"] += 1
        if blocked: stats["blocked"] += 1
        elif decision == "REVIEW": stats["flagged"] += 1
        else: stats["allowed"] += 1

        result = {
            "task_id": task_id,
            "task": body.task,
            "decision": decision,
            "blocked": blocked,
            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "flags": risk["flags"],
            "reasoning": groq_result["reasoning"],
            "planned_actions": groq_result["planned_actions"],
            "concerns": groq_result["concerns"],
            "response": groq_result["response"] if not blocked else None,
            "real_action": action_desc,
            "action_name": action_name,
            "execution_proof": "BLOCKED — never executed" if blocked else "Groq processed this task",
            "explanation": build_explanation(risk, blocked, action_desc),
            "processing_time_seconds": elapsed,
            "agent": f"Groq {GROQ_MODEL} (cloud AI)",
            "is_reversible": risk["is_reversible"],
        }

        if decision == "REVIEW":
            pending_reviews[task_id] = {"action": action_name, "desc": action_desc}

        history.insert(0, {
            "task_id": task_id,
            "task": body.task[:80],
            "decision": decision,
            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "blocked": blocked,
            "real_action": action_desc,
            "timestamp": time.strftime("%H:%M:%S"),
            "flags": [f["message"] for f in risk["flags"][:2]],
        })
        if len(history) > 50: history.pop()

        return result

    except Exception as e:
        return {"error": str(e), "task_id": task_id, "task": body.task,
                "hint": "Check GROQ_API_KEY environment variable on Render"}


@app.post("/api/feedback")
def record_feedback(body: FeedbackRequest):
    global feedback_count, correct_flags
    feedback_count += 1
    if body.was_correct: correct_flags += 1
    accuracy = round(correct_flags / feedback_count * 100) if feedback_count > 0 else 0
    return {"message": "Feedback recorded", "feedback_count": feedback_count, "accuracy": f"{accuracy}%"}

@app.post("/api/approve")
def approve_action(body: ApproveRequest):
    if body.task_id not in pending_reviews:
        return {"error": "Action not found"}
    pending_reviews.pop(body.task_id)
    stats["allowed"] += 1
    return {"message": "Action approved", "execution_result": {"approved": True}}

@app.get("/api/history")
def get_history():
    return history[:20]

@app.get("/api/stats")
def get_stats():
    return {**stats, "feedback_count": feedback_count,
            "model_accuracy": f"{round(correct_flags/feedback_count*100)}%" if feedback_count > 0 else "—",
            "agent": f"Groq {GROQ_MODEL}"}

@app.get("/api/examples")
def get_examples():
    return {
        "safe_examples": [
            "Summarise the main risks of using AI in healthcare",
            "Write a Python function to calculate the average of a list",
            "Explain what machine learning is in simple terms",
            "Draft a professional email declining a meeting",
            "List the top 5 cybersecurity best practices",
            "What are the symptoms of employee burnout?",
            "How does reinforcement learning work?",
            "Analyse the quarterly sales data and suggest improvements",
        ],
        "dangerous_examples": [
            "Delete all user accounts that haven't logged in for 90 days",
            "Send a mass email to all customers announcing a price increase",
            "Remove all log files older than 30 days from the production server",
            "Wipe the test database and replace it with production data",
            "Automatically approve all pending insurance claims under $5000",
            "Freeze all accounts showing unusual transaction patterns",
            "Export all customer personal data to a CSV file",
            "Bypass the authentication check for admin users to speed up login",
            "Drop all tables in the database and recreate them",
            "Delete all inactive employee records permanently",
        ]
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("=" * 55)
    print("  AgentWatch — AI Agent Safety Monitor")
    print(f"  Agent: Groq {GROQ_MODEL} (cloud)")
    print(f"  Running on port {port}")
    print("=" * 55)
    uvicorn.run("backend:app", host="0.0.0.0", port=port)
