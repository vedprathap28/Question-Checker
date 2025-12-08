from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Dict, Optional

import pandas as pd
import re
import io
import time
from fuzzywuzzy import fuzz

import utils
from database import Base, engine, SessionLocal
import crud

# ============================================================
# DB INIT
# ============================================================
Base.metadata.create_all(bind=engine)

# ============================================================
# APP INIT
# ============================================================
app = FastAPI(title="Question Checker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Question Checker API is running"}


# ============================================================
# Google Sheets retry wrapper (handles 429)
# ============================================================
def gs_retry(fn, max_tries: int = 5, base_sleep: float = 1.5):
    last_err = None
    for i in range(max_tries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            msg = repr(e)
            if ("429" in msg) or ("Quota exceeded" in msg) or ("Read requests" in msg):
                time.sleep(base_sleep * (2 ** i))
                continue
            raise
    raise last_err


# ============================================================
# UNIVERSAL CSV QUESTION EXTRACTOR
# ============================================================
def parse_any_csv_questions(content_bytes: bytes, dedupe: bool = True) -> List[Dict]:
    """
    Extracts question candidates from ANY CSV-like structure.

    dedupe=True  -> remove duplicates (useful for import/master)
    dedupe=False -> keep duplicates (required for /check/new duplicate detection)
    """
    df = pd.read_csv(
        io.BytesIO(content_bytes),
        header=None,
        dtype=str,
        keep_default_na=False,
        on_bad_lines="skip",
        engine="python"
    )
    rows, cols = df.shape

    def cell(r, c) -> str:
        v = df.iat[r, c]
        return "" if v is None else str(v).strip()

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", str(s).strip().lower())

    def marks_from_text(s: str) -> Optional[int]:
        m = re.match(r"^\s*(\d+)\s*marks?\s*$", norm(s))
        if m:
            return int(m.group(1))
        return None

    def question_confidence(text: str) -> float:
        t = (text or "").strip()
        if not t:
            return 0.0

        low = norm(t)

        junk = {
            "question", "questions", "answer", "answers",
            "unit", "unit name", "topic",
            "bloom", "blooms taxonomy", "bloom taxonomy",
            "marks", "mark", "sl.no", "s.no", "sno"
        }
        if low in junk:
            return 0.0

        if len(low) < 8:
            return 0.0

        score = 0.2

        if low.endswith("?"):
            score += 0.4

        starters = ("what", "why", "how", "define", "explain", "write", "list",
                    "describe", "differentiate", "compare", "state", "give")
        if low.startswith(starters):
            score += 0.3

        words = low.split()
        if len(words) >= 6:
            score += 0.2
        if len(words) >= 10:
            score += 0.1

        digits = sum(ch.isdigit() for ch in low)
        if digits > len(low) * 0.3:
            score -= 0.3

        return max(0.0, min(1.0, score))

    # detect header rows containing "question"
    header_rows = []
    for r in range(min(rows, 120)):
        row_vals = [norm(cell(r, c)) for c in range(cols)]
        if any("question" in v for v in row_vals):
            header_rows.append(r)

    blocks = []
    if header_rows:
        best = max(header_rows, key=lambda rr: sum("question" in norm(cell(rr, c)) for c in range(cols)))
        hdr = [norm(cell(best, c)) for c in range(cols)]

        for c in range(cols):
            if "question" in hdr[c]:
                a_col = b_col = u_col = m_col = None
                for k in range(c + 1, min(c + 12, cols)):
                    hv = hdr[k]
                    if a_col is None and "answer" in hv:
                        a_col = k
                    if b_col is None and "bloom" in hv:
                        b_col = k
                    if u_col is None and ("unit" in hv or "topic" in hv):
                        u_col = k
                    if m_col is None and ("mark" in hv or "marks" in hv or "score" in hv):
                        m_col = k
                blocks.append({"q": c, "a": a_col, "b": b_col, "u": u_col, "m": m_col})

        seen = set()
        uniq = []
        for b in blocks:
            if b["q"] not in seen:
                uniq.append(b)
                seen.add(b["q"])
        blocks = uniq

    current_marks: Optional[int] = None
    out: List[Dict] = []

    if blocks:
        for r in range(rows):
            for c in range(cols):
                mm = marks_from_text(cell(r, c))
                if mm is not None:
                    current_marks = mm
                    break

            for b in blocks:
                q = cell(r, b["q"])
                conf = question_confidence(q)
                if conf < 0.45:
                    continue

                a = cell(r, b["a"]) if b["a"] is not None else ""
                bloom = cell(r, b["b"]) if b["b"] is not None else ""
                unit = cell(r, b["u"]) if b["u"] is not None else ""
                marks_raw = cell(r, b["m"]) if b["m"] is not None else (str(current_marks) if current_marks else "")

                out.append({
                    "question": q,
                    "answer": a,
                    "bloom": bloom,
                    "unit": unit,
                    "marks_raw": marks_raw,
                    "confidence": conf
                })
    else:
        for r in range(rows):
            for c in range(cols):
                txt = cell(r, c)

                mm = marks_from_text(txt)
                if mm is not None:
                    current_marks = mm
                    continue

                conf = question_confidence(txt)
                if conf < 0.65:
                    continue

                out.append({
                    "question": txt,
                    "answer": "",
                    "bloom": "",
                    "unit": "",
                    "marks_raw": str(current_marks) if current_marks else "",
                    "confidence": conf
                })

    if not dedupe:
        return out

    seen_q = set()
    cleaned = []
    for r in out:
        key = re.sub(r"\s+", " ", r["question"].strip().lower())
        if not key or key in seen_q:
            continue
        seen_q.add(key)
        cleaned.append(r)

    return cleaned


# ============================================================
# CLASSIFY SIMILARITY
# ============================================================
def classify_similarity(score: float) -> str:
    if score >= 95:
        return "duplicate"
    if score >= 50:
        return "reframed"
    return "new"


def band_label(score: float) -> str:
    if score >= 95:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


# ============================================================
# IMPORT PREVIOUS ASSESSMENT
# ============================================================
@app.post("/import/assessment")
async def import_assessment(
    assessment_name: str = Form(...),
    file: UploadFile = File(...)
):
    db: Session = SessionLocal()
    assessment = crud.create_assessment(db, assessment_name)

    content = await file.read()
    extracted = parse_any_csv_questions(content, dedupe=True)

    total_found = len(extracted)
    total_saved = 0

    for r in extracted:
        q_text = r["question"]
        marks = utils.normalize_marks(r.get("marks_raw", "")) or 0
        unit_name = (r.get("unit") or "").strip() or "Unknown Unit"

        topic = crud.get_or_create_topic(db, unit_name)
        _, added = crud.add_assessment_question(
            db=db,
            assessment_id=assessment.id,
            topic_id=topic.id,
            marks=marks,
            question_text=q_text,
        )
        if added:
            total_saved += 1

    db.close()

    return {
        "assessment_name": assessment_name,
        "total_question_candidates_found": total_found,
        "questions_saved_to_db": total_saved,
        "message": "Assessment import complete."
    }


# ============================================================
# CHECK NEW ASSESSMENT AGAINST DB + DUPLICATES IN SAME CSV
# + show matched assessment/college name
# ============================================================
@app.post("/check/new")
async def check_new_assessment(
    file: UploadFile = File(...),
    assessment_name: str = Form(...),
):
    content = await file.read()

    # keep duplicates for duplicate detection inside uploaded paper
    new_rows = parse_any_csv_questions(content, dedupe=False)

    if not new_rows:
        return {"error": "No valid questions found in uploaded file."}

    # Duplicate within uploaded paper
    seen = {}
    dup_flags: List[Dict] = []
    for r in new_rows:
        q = (r.get("question") or "").strip()
        key = utils.normalize(q)
        if key in seen:
            dup_flags.append({"duplicate": True, "duplicate_question": seen[key]})
        else:
            seen[key] = q
            dup_flags.append({"duplicate": False, "duplicate_question": ""})

    dup_count = sum(1 for d in dup_flags if d["duplicate"])

    db = SessionLocal()
    prev_pairs = crud.get_all_previous_questions_with_assessment(db)
    db.close()

    details = []
    for idx, r in enumerate(new_rows):
        q_new = r["question"]
        marks = utils.normalize_marks(r.get("marks_raw", ""))

        best_score = 0.0
        best_prev = ""
        best_assessment = ""

        for prev_q, prev_assessment in prev_pairs:
            score = utils.similarity_percentage(q_new, prev_q)
            if score > best_score:
                best_score = score
                best_prev = prev_q
                best_assessment = prev_assessment

        category = classify_similarity(best_score)
        band = band_label(best_score)

        details.append({
            "new_question": q_new,
            "closest_previous_question": best_prev,
            "similarity_percentage": round(best_score, 2),
            "band": band,
            "category": category,
            "unit": r.get("unit", ""),
            "marks": marks,
            "confidence": round(float(r.get("confidence", 0.0)), 2),

            # Requested columns
            "duplicate": dup_flags[idx]["duplicate"],
            "duplicate_question": dup_flags[idx]["duplicate_question"],

            # Requested: show the matched paper/college name
            "matched_college": best_assessment if best_score >= 50 else "",
        })

    overall = sum(d["similarity_percentage"] for d in details) / len(details)

    return {
        "assessment_name": assessment_name,
        "total_new_questions": len(details),
        "overall_similarity_percentage": round(overall, 1),
        "duplicates_within_uploaded_paper": dup_count,
        "details": details
    }


# ============================================================
# CHECK AGAINST MASTER SHEET
# ============================================================
@app.post("/check/master")
async def check_against_master(
    file: UploadFile = File(...),
    master_sheet_url: str = Form(utils.MASTER_SHEET_URL_DEFAULT),
    master_tab_name: str = Form(utils.MASTER_TAB_DEFAULT),
):
    content = await file.read()
    extracted = parse_any_csv_questions(content, dedupe=True)

    if not extracted:
        return {"error": "No valid questions found in uploaded file."}

    try:
        unit_map = gs_retry(lambda: utils.build_unit_map_from_master(master_sheet_url, master_tab_name))
    except Exception as e:
        return {"error": f"Failed reading master sheet: {repr(e)}"}

    unit_keys = list(unit_map.keys())

    results = []
    added_new = 0
    added_reframed = 0
    skipped = 0
    unit_open_errors = 0

    unit_ss_cache = {}          # url -> spreadsheet
    unit_ws_cache = {}          # url -> {norm_title: worksheet}
    unit_existing_cache = {}    # url -> list[str]
    unit_header_cache = {}      # (url, marks) -> header

    def get_marks_ws_from_cache(unit_sheet_url: str, unit_ss, marks: int):
        if unit_sheet_url not in unit_ws_cache:
            wss = gs_retry(lambda: unit_ss.worksheets())
            unit_ws_cache[unit_sheet_url] = {utils._norm_title(w.title): w for w in wss}

        title_map = unit_ws_cache[unit_sheet_url]
        aliases = set(utils._norm_title(x) for x in utils.MARKS_TITLE_ALIASES.get(marks, []))
        for a in aliases:
            if a in title_map:
                return title_map[a]
        raise ValueError(f"Marks sheet for {marks} not found in unit sheet.")

    for item in extracted:
        q = (item.get("question") or "").strip()
        if not q:
            continue

        unit_name = (item.get("unit") or "").strip()
        marks = utils.normalize_marks(item.get("marks_raw", ""))

        if not unit_name:
            results.append({"question": q, "unit": "", "marks": marks, "status": "error", "message": "Unit missing"})
            continue

        if marks not in (2, 4, 8, 16):
            results.append({"question": q, "unit": unit_name, "marks": marks, "status": "error", "message": "Marks not 2/4/8/16"})
            continue

        # fuzzy match unit name to master keys
        best_key = None
        best_score = 0
        for k in unit_keys:
            sc = fuzz.ratio(unit_name.lower(), k.lower())
            if sc > best_score:
                best_score = sc
                best_key = k

        if not best_key or best_score < 80:
            results.append({"question": q, "unit": unit_name, "marks": marks, "status": "error",
                            "message": f"Unit not found (best={best_key}, score={best_score})"})
            continue

        unit_sheet_url = unit_map[best_key]

        try:
            if unit_sheet_url not in unit_ss_cache:
                unit_ss_cache[unit_sheet_url] = gs_retry(lambda: utils.open_sheet_by_url(unit_sheet_url))
            unit_ss = unit_ss_cache[unit_sheet_url]
        except Exception as e:
            unit_open_errors += 1
            results.append({"question": q, "unit": best_key, "marks": marks, "status": "error",
                            "message": f"Unit sheet open failed: {repr(e)}"})
            continue

        try:
            marks_ws = get_marks_ws_from_cache(unit_sheet_url, unit_ss, marks)
        except Exception as e:
            results.append({"question": q, "unit": best_key, "marks": marks, "status": "error",
                            "message": f"Marks worksheet missing: {repr(e)}"})
            continue

        # cache existing questions once per unit sheet
        if unit_sheet_url not in unit_existing_cache:
            existing_questions = []
            for mk in (2, 4, 8, 16):
                try:
                    ws = get_marks_ws_from_cache(unit_sheet_url, unit_ss, mk)
                    existing_questions.extend(gs_retry(lambda ws=ws: utils.read_questions_from_ws(ws)))
                except Exception:
                    pass

            try:
                rws_existing = gs_retry(lambda: unit_ss.worksheet(utils.REFRAME_SHEET_NAME))
                existing_questions.extend(gs_retry(lambda: utils.read_questions_from_ws(rws_existing)))
            except Exception:
                pass

            unit_existing_cache[unit_sheet_url] = existing_questions

        existing_questions = unit_existing_cache[unit_sheet_url]

        best_sim = 0.0
        best_match_q = ""
        for prev in existing_questions:
            sc = utils.similarity_percentage(q, prev)
            if sc > best_sim:
                best_sim = sc
                best_match_q = prev

        cat = classify_similarity(best_sim)
        band = band_label(best_sim)

        if cat == "duplicate":
            skipped += 1
            results.append({"question": q, "unit": best_key, "marks": marks, "similarity_percentage": round(best_sim, 2),
                            "band": band, "category": cat, "action": "skipped", "closest_question": best_match_q})
            continue

        header_key = (unit_sheet_url, marks)
        if header_key not in unit_header_cache:
            unit_header_cache[header_key] = gs_retry(lambda: utils.get_header(marks_ws))
        header = unit_header_cache[header_key]

        row_to_write = utils.build_row_for_append(header, item)

        if cat == "new":
            try:
                gs_retry(lambda: marks_ws.append_row(row_to_write))
                added_new += 1
                unit_existing_cache[unit_sheet_url].append(q)
                results.append({"question": q, "unit": best_key, "marks": marks, "similarity_percentage": round(best_sim, 2),
                                "band": band, "category": cat, "action": f"added_to_{marks}_marks", "closest_question": best_match_q})
            except Exception as e:
                results.append({"question": q, "unit": best_key, "marks": marks, "status": "error",
                                "message": f"Append failed: {repr(e)}"})

        elif cat == "reframed":
            try:
                rws = gs_retry(lambda: utils.get_or_create_reframed_sheet(unit_ss))
                rws_header = gs_retry(lambda: utils.get_header(rws))
                gs_retry(lambda: rws.append_row(utils.build_row_for_append(rws_header, item)))
                added_reframed += 1
                unit_existing_cache[unit_sheet_url].append(q)
                results.append({"question": q, "unit": best_key, "marks": marks, "similarity_percentage": round(best_sim, 2),
                                "band": band, "category": cat, "action": "added_to_reframed_questions", "closest_question": best_match_q})
            except Exception as e:
                results.append({"question": q, "unit": best_key, "marks": marks, "status": "error",
                                "message": f"Reframed append failed: {repr(e)}"})

    return {
        "master_sheet_url": master_sheet_url,
        "master_tab_name": master_tab_name,
        "total_extracted_questions": len(extracted),
        "added_new": added_new,
        "added_reframed": added_reframed,
        "skipped_duplicates": skipped,
        "unit_open_errors": unit_open_errors,
        "details": results,
    }


# ============================================================
# ASSESSMENTS LIST + DETAILS + DELETE
# ============================================================
@app.get("/assessments")
def list_assessments():
    db = SessionLocal()
    assessments = crud.get_all_assessments(db)
    db.close()
    return [{"id": a.id, "name": a.name} for a in assessments]


@app.get("/assessments/{assessment_id}")
def get_assessment_details(assessment_id: int):
    db = SessionLocal()
    assessment = crud.get_assessment_by_id(db, assessment_id)
    if not assessment:
        db.close()
        return {"error": "Assessment not found"}

    questions = crud.get_questions_by_assessment(db, assessment_id)
    db.close()

    return {
        "assessment_id": assessment.id,
        "assessment_name": assessment.name,
        "questions": [
            {
                "question_text": q.question_text,
                "topic": q.topic.name if getattr(q, "topic", None) else "",
                "marks": q.marks,
            }
            for q in questions
        ]
    }


@app.delete("/assessments/{assessment_id}")
def delete_assessment(assessment_id: int):
    db = SessionLocal()
    ok = crud.delete_assessment(db, assessment_id)
    db.close()
    if ok:
        return {"message": "Assessment deleted"}
    return {"error": "Assessment not found"}
