"""Wellora AI backend (FastAPI). Run: uvicorn main:app --reload  (from /backend)
Demo login stores nothing. Gemini key stays here (server-side). Works without a key via safe local fallbacks."""
import os, re, json
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv; load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

KEY = os.getenv("GEMINI_API_KEY", "")
if KEY == "your_key_here": KEY = ""
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
app = FastAPI(title="Wellora AI")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # local demo: lets a double-clicked HTML file call the API
CATS = {"hydration", "meal", "break", "sleep", "movement", "mindfulness", "task"}
HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MED = re.compile(r"diagnos|prescri|dosage|\bdose\b|tablet|medicine|medication|antibiotic|insulin|symptom|pregnan|cancer|diabet|blood pressure|दवा|दवाई|बीमारी|इलाज|लक्षण|डोज़", re.I)
EMG = re.compile(r"suicid|self.?harm|kill myself|overdose|can.?t breathe|heart attack|आत्महत्या|सांस नहीं", re.I)

class Session(BaseModel):
    name: str = Field("Guest", max_length=40); email: str | None = Field(None, max_length=80)
class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=500); lang: str = "en"; name: str = Field("", max_length=40); focus: list[str] = []; level: str = Field("", max_length=20)
class PlanReq(BaseModel):
    lang: str = "en"; focus: list[str] = []; wake: str = "07:00"; sleep: str = "23:00"; level: str = Field("beginner", max_length=20); diet: str = Field("", max_length=20)

async def gemini(prompt: str, as_json=False):
    if not KEY: return None
    cfg = {"temperature": 0.6, "maxOutputTokens": 3000}
    if as_json: cfg["responseMimeType"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                             headers={"x-goog-api-key": KEY}, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None  # never log private content

TIPS = {
    "en": {"water": "Keep a bottle at your desk and sip a little every hour.", "sleep": "Try a 30-minute screen-free wind-down before your usual bedtime.",
           "break": "Every 45–60 minutes, look away from the screen for a minute and stretch if you can.", "stress": "Try 5 slow breaths: in for 4, out for 6. Small steps count.",
           "workout": "Gentle 20-minute session: 5 min easy walk, 10 min stretching or a yoga flow, 5 min slow breathing. Stop if anything hurts.", "default": "Pick one small step for today, like a glass of water or a 5-minute walk. Add it to your Plan and tick it off."},
    "hi": {"water": "अपने पास पानी की बोतल रखें और हर घंटे थोड़ा-थोड़ा पिएँ।", "sleep": "सोने से 30 मिनट पहले स्क्रीन बंद करके आराम करने की कोशिश करें।",
           "break": "हर 45–60 मिनट में एक मिनट स्क्रीन से नज़र हटाएँ और हो सके तो स्ट्रेच करें।", "stress": "5 धीमी साँसें लें: 4 गिनती में अंदर, 6 में बाहर। छोटे कदम भी मायने रखते हैं।",
           "workout": "20 मिनट का हल्का सत्र: 5 मिनट धीमी सैर, 10 मिनट स्ट्रेचिंग या योग, 5 मिनट धीमी साँसें। कुछ दर्द हो तो रुक जाएँ।", "default": "आज के लिए एक छोटा कदम चुनें, जैसे एक गिलास पानी या 5 मिनट की सैर। उसे Plan में जोड़ें और टिक करें।"}}
NOTE = {"en": "General wellness information, not medical advice.", "hi": "यह सामान्य वेलनेस जानकारी है, चिकित्सा सलाह नहीं।"}

def local_reply(m: str, lang: str):
    t = TIPS.get(lang, TIPS["en"]); s = m.lower()
    k = "workout" if re.search(r"workout|exercise|व्यायाम|कसरत", s) else "water" if re.search(r"water|hydrat|पानी", s) else "sleep" if re.search(r"sleep|नींद|सोना", s) else "break" if re.search(r"break|screen|eye|ब्रेक|आँख", s) else "stress" if re.search(r"stress|anxi|tension|तनाव|चिंता", s) else "default"
    return t[k]

@app.get("/api/health")
def health(): return {"ok": True, "ai": "gemini" if KEY else "local-fallback"}

@app.post("/api/demo/session")
def session(b: Session):  # demo only: nothing stored, no password, not real authentication
    return {"ok": True, "name": b.name.strip() or "Guest"}

@app.post("/api/ai/chat")
async def chat(b: Chat):
    lang = b.lang if b.lang in ("en", "hi") else "en"
    if EMG.search(b.message):
        msg = ("If you may be in danger, please call 112 (India) or reach a trusted person right now. You deserve support." if lang == "en"
               else "अगर आप खतरे में हैं, तो अभी 112 पर कॉल करें या किसी भरोसेमंद व्यक्ति से संपर्क करें। आप सहायता के हक़दार हैं।")
        return {"reply": msg, "note": NOTE[lang], "source": "safety"}
    if MED.search(b.message):
        msg = ("I can't diagnose or advise on medicines or symptoms. Please talk to a qualified doctor or pharmacist. I can help with simple routine habits instead." if lang == "en"
               else "मैं बीमारी, लक्षण या दवा पर सलाह नहीं दे सकता। कृपया किसी योग्य डॉक्टर या फ़ार्मासिस्ट से बात करें। मैं रोज़ की आदतों में मदद कर सकता हूँ।")
        return {"reply": msg, "note": NOTE[lang], "source": "safety"}
    prompt = ("You are Wellora, a warm India-first wellness-routine assistant. Reply in the user's language (English, Hindi or Hinglish), max 100 words, practical and kind. "
              "Never diagnose, prescribe, suggest medicines, calorie limits, fasting, weight-loss targets or extreme exercise; point medical concerns to a doctor. Keep any exercise suggestions gentle and low-risk. "
              f"User name: {b.name or 'friend'}. Focus areas: {', '.join(b.focus[:6]) or 'none'}. Fitness level: {b.level if b.level in ('beginner', 'regular') else 'unspecified'}.\nUser: {b.message}")
    out = await gemini(prompt)
    return {"reply": (out or local_reply(b.message, lang)).strip(), "note": NOTE[lang], "source": "gemini" if out else "local"}

def starter(focus, wake, sleep, lang):
    h = int(wake[:2]); hi = lang == "hi"
    T = lambda en, hn: hn if hi else en
    pool = {"hydration": (f"{h:02d}:15", T("Drink a glass of water", "एक गिलास पानी पिएँ"), 2),
            "meal": ("13:00", T("Have a regular lunch", "समय पर दोपहर का भोजन करें"), 20),
            "break": ("15:30", T("Short screen break", "स्क्रीन से छोटा ब्रेक लें"), 5),
            "movement": ("18:00", T("Enjoyable walk or stretch", "सैर या स्ट्रेचिंग करें"), 15),
            "mindfulness": ("21:00", T("5 slow breaths", "5 धीमी साँसें लें"), 5),
            "sleep": (f"{max(int(sleep[:2]) - 1, 0):02d}:{sleep[3:]}", T("Screen-free wind-down", "सोने से पहले स्क्रीन बंद करें"), 30)}
    keys = [k for k in focus if k in pool] or ["hydration", "break", "sleep"]
    return [{"title": pool[k][1], "category": k, "time": pool[k][0], "dur": pool[k][2], "why": T("Based on your chosen focus", "आपके चुने फ़ोकस के अनुसार")} for k in keys]

def clean(items):
    out, seen = [], set()
    for i in items if isinstance(items, list) else []:
        try:
            t = str(i["title"]).strip()[:80]; c = i.get("category", "task"); tm = str(i["time"]); d = int(i.get("dur", 5))
        except Exception:
            continue
        if not t or t.lower() in seen or c not in CATS or not HM.match(tm) or not 0 <= d <= 120 or MED.search(t) or re.search(r"calorie|fast(ing)?\b|diet plan|weight loss|उपवास", t, re.I):
            continue
        seen.add(t.lower()); out.append({"title": t, "category": c, "time": tm, "dur": d, "why": str(i.get("why", ""))[:80]})
    return out[:12]

@app.post("/api/ai/plan")
async def plan(b: PlanReq):
    lang = b.lang if b.lang in ("en", "hi") else "en"
    wake = b.wake if HM.match(b.wake) else "07:00"; sleep = b.sleep if HM.match(b.sleep) else "23:00"
    prompt = (f"Draft a gentle daily wellness routine as JSON only: a list of up to 8 objects with keys title (max 60 chars), category (one of {sorted(CATS)}), time (HH:MM 24h), dur (minutes 0-60), why (short). "
              f"Fitness level: {b.level if b.level in ('beginner', 'regular') else 'beginner'}. Food preference: {b.diet if b.diet in ('veg', 'nonveg', 'egg') else 'any'}. Language: {'Hindi' if lang == 'hi' else 'English'}. Wake {wake}, sleep {sleep}. Focus: {', '.join(b.focus[:6]) or 'general'}. Indian everyday context. "
              "No medical advice, calorie limits, fasting, weight-loss or intense exercise.")
    raw = await gemini(prompt, as_json=True); items = []
    if raw:
        try: items = clean(json.loads(re.sub(r"^```(json)?|```$", "", raw.strip()).strip()))
        except Exception: items = []
    return {"items": items or clean(starter(b.focus, wake, sleep, lang)), "source": "gemini" if items else "local"}

from stream import router as stream_router
app.include_router(stream_router)  # streaming, profile-aware chat

app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="ui")
