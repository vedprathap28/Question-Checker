import re
import difflib
import os
from typing import List, Dict, Optional, Tuple, Any

import gspread
from google.oauth2.service_account import Credentials

# =========================
# CONFIG
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MASTER_SHEET_URL_DEFAULT = "https://docs.google.com/spreadsheets/d/1PkpwXzHnBYNK6qXhniABIys_RodW74G2d-7dcrrVrUc/edit"
MASTER_TAB_DEFAULT = "Programming Foundations Descriptive"

REFRAME_SHEET_NAME = "Reframed Questions"
REFRAME_HEADER = ["Question", "Answer", "Bloom's Taxonomy Level"]


# =========================
# TEXT + SIMILARITY
# =========================
def normalize(text: str) -> str:
    s = "" if text is None else str(text)
    s = s.strip().lower()
    return re.sub(r"\s+", " ", s)


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).strip())


def clean_lower(text: Any) -> str:
    return clean_text(text).lower()


def similarity_percentage(a: str, b: str) -> float:
    a = clean_lower(a)
    b = clean_lower(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def best_fuzzy_match(target: str, options: List[str]) -> Tuple[str, float]:
    best = ""
    best_score = 0.0
    for opt in options:
        sc = similarity_percentage(target, opt)
        if sc > best_score:
            best_score = sc
            best = opt
    return best, best_score


# =========================
# MARKS
# =========================
def normalize_marks(raw) -> Optional[int]:
    if raw is None:
        return None
    t = clean_lower(raw)
    m = re.search(r"\b(2|4|8|16)\b", t)
    if m:
        return int(m.group(1))
    words = {"two": 2, "four": 4, "eight": 8, "sixteen": 16}
    for w, v in words.items():
        if w in t:
            return v
    return None


# =========================
# GOOGLE SHEETS AUTH
# =========================
def get_gspread_client():
    print("SERVICE_ACCOUNT_FILE =", SERVICE_ACCOUNT_FILE)
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"service_account.json not found at: {SERVICE_ACCOUNT_FILE}")

    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def extract_spreadsheet_id(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not m:
        raise ValueError(f"Invalid Google Sheet URL: {url}")
    return m.group(1)


def open_sheet_by_url(url: str):
    ss_id = extract_spreadsheet_id(url)
    client = get_gspread_client()
    try:
        return client.open_by_key(ss_id)
    except Exception as e:
        raise PermissionError(f"open_by_key failed for {ss_id}: {repr(e)}")


# =========================
# MASTER LOOKUP (Topic -> Sheet link)
# =========================
def build_unit_map_from_master(master_url: str, tab_name: str) -> Dict[str, str]:
    ss = open_sheet_by_url(master_url)

    try:
        ws = ss.worksheet(tab_name)
    except Exception:
        wanted = clean_lower(tab_name).strip()
        titles = [w.title for w in ss.worksheets()]
        titles_lower = [clean_lower(t).strip() for t in titles]

        if wanted in titles_lower:
            ws = ss.worksheet(titles[titles_lower.index(wanted)])
        else:
            best_title, best_score = best_fuzzy_match(wanted, titles_lower)
            if best_score < 70:
                raise ValueError(
                    f"Master tab not found. Requested='{tab_name}'. Available tabs={titles}"
                )
            real_title = titles[titles_lower.index(best_title)]
            ws = ss.worksheet(real_title)

    values = ws.get_all_values()
    if not values or len(values) < 2:
        raise ValueError("Master sheet tab is empty or not readable.")

    headers = [clean_lower(h) for h in values[0]]

    def idx(col_name: str) -> int:
        cn = clean_lower(col_name).strip()
        if cn not in headers:
            raise ValueError(f"Column '{col_name}' not found in headers: {headers}")
        return headers.index(cn)

    topic_i = idx("Topic")
    link_i = idx("Sheet link")

    unit_map: Dict[str, str] = {}
    for row in values[1:]:
        if len(row) <= max(topic_i, link_i):
            continue
        topic = clean_text(row[topic_i])
        link = clean_text(row[link_i])
        if topic and link.startswith("http"):
            unit_map[topic] = link

    if not unit_map:
        raise ValueError("No unit mappings found (Topic / Sheet link).")

    return unit_map


# =========================
# UNIT SHEET HELPERS
# =========================
def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_lower(t))


MARKS_TITLE_ALIASES = {
    2: ["2marks", "2mark", "2", "twomarks", "two"],
    4: ["4marks", "4mark", "4", "fourmarks", "four"],
    8: ["8marks", "8mark", "8", "eightmarks", "eight"],
    16: ["16marks", "16mark", "16", "sixteenmarks", "sixteen"],
}


def find_marks_worksheet(unit_spreadsheet, marks: int):
    aliases = set(_norm_title(x) for x in MARKS_TITLE_ALIASES.get(marks, []))
    for ws in unit_spreadsheet.worksheets():
        if _norm_title(ws.title) in aliases:
            return ws
    raise ValueError(f"Marks sheet for {marks} not found in unit sheet.")


def get_header(ws) -> List[str]:
    return [clean_text(h) for h in ws.row_values(1)]


def find_question_col_index(header: List[str]) -> int:
    lowered = [clean_lower(h) for h in header]
    if "question" in lowered:
        return lowered.index("question")
    for i, h in enumerate(lowered):
        if "question" in h:
            return i
    return 0


def read_questions_from_ws(ws) -> List[str]:
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return []

    header = [clean_text(x) for x in values[0]]
    q_i = find_question_col_index(header)

    out: List[str] = []
    for row in values[1:]:
        if q_i >= len(row):
            continue
        q = clean_text(row[q_i])
        if not q:
            continue
        if clean_lower(q) in ("question", "questions"):
            continue
        out.append(q)

    return out


def get_or_create_reframed_sheet(unit_spreadsheet):
    """
    Always enforce clean A1:C header like screenshot-1.
    """
    try:
        ws = unit_spreadsheet.worksheet(REFRAME_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = unit_spreadsheet.add_worksheet(title=REFRAME_SHEET_NAME, rows=2000, cols=10)

    existing = ws.row_values(1)
    existing_first3 = [clean_text(x) for x in existing[:3]]

    if existing_first3 != REFRAME_HEADER:
        ws.clear()
        ws.update("A1:C1", [REFRAME_HEADER])

    return ws


def build_row_for_append(target_header: List[str], item: Dict[str, str]) -> List[str]:
    q_val = clean_text(item.get("question", ""))
    a_val = clean_text(item.get("answer", ""))
    b_val = clean_text(item.get("bloom", ""))

    header_first3 = [clean_text(h) for h in target_header[:3]]
    if header_first3 == REFRAME_HEADER:
        return [q_val, a_val, b_val]

    lowered = [clean_lower(h) for h in target_header]
    row = [""] * len(target_header)

    q_i = find_question_col_index(target_header)
    row[q_i] = q_val

    for i, h in enumerate(lowered):
        if "answer" in h:
            row[i] = a_val
            break

    for i, h in enumerate(lowered):
        if "bloom" in h:
            row[i] = b_val
            break

    return row
