import re
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Zamala QBank Pro", layout="wide")

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR_CANDIDATES = [
    SCRIPT_DIR,
    SCRIPT_DIR / "data",
    SCRIPT_DIR.parent / "data",
]
APPDATA_DIR = SCRIPT_DIR / "appdata"
APPDATA_DIR.mkdir(parents=True, exist_ok=True)

ATTEMPTS_SUMMARY_PATH = APPDATA_DIR / "attempts_summary.csv"
ATTEMPT_ANSWERS_PATH = APPDATA_DIR / "attempt_answers.csv"

SUMMARY_COLUMNS = [
    "attempt_id",
    "timestamp",
    "mode",
    "bank_label",
    "topic_filter",
    "question_count",
    "answered_count",
    "score",
    "percentage",
]

ANSWER_COLUMNS = [
    "attempt_id",
    "timestamp",
    "mode",
    "bank_label",
    "question_uid",
    "question_id",
    "topic",
    "user_answer",
    "correct_answer",
    "is_correct",
]

OPTION_COLUMN_LABELS = [
    ("option_a", "A"),
    ("option_b", "B"),
    ("option_c", "C"),
    ("option_d", "D"),
    ("option_e", "E"),
    ("option_f", "F"),
]

IMAGE_COLUMN_CANDIDATES = [
    "image",
    "image_path",
    "image_file",
    "image_url",
    "figure",
    "figure_path",
    "media",
    "asset_path",
]


def normalize_text(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def normalize_answer(x) -> str:
    x = normalize_text(x).upper()
    for old, new in [(";", ","), ("/", ","), ("|", ",")]:
        x = x.replace(old, new)
    x = x.replace(" ", "")
    while ",," in x:
        x = x.replace(",,", ",")
    return x.strip(",")


def split_answer_letters(x) -> list[str]:
    cleaned = normalize_answer(x)
    if not cleaned:
        return []
    return [part for part in cleaned.split(",") if part]


def compare_answers(user_answer, correct_answer, ordered: bool = False) -> bool:
    if ordered:
        return normalize_answer(user_answer) == normalize_answer(correct_answer)
    return sorted(set(split_answer_letters(user_answer))) == sorted(set(split_answer_letters(correct_answer)))


def csv_has_any_content(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except Exception:
        return False


def ensure_csv_schema(path: Path, required_columns: list[str]):
    if not path.exists():
        pd.DataFrame(columns=required_columns).to_csv(path, index=False)
        return

    try:
        df = pd.read_csv(path).fillna("")
    except Exception:
        pd.DataFrame(columns=required_columns).to_csv(path, index=False)
        return

    changed = False
    for col in required_columns:
        if col not in df.columns:
            df[col] = ""
            changed = True

    df = df[required_columns + [c for c in df.columns if c not in required_columns]]
    if changed:
        df.to_csv(path, index=False)


def ensure_history_files():
    ensure_csv_schema(ATTEMPTS_SUMMARY_PATH, SUMMARY_COLUMNS)
    ensure_csv_schema(ATTEMPT_ANSWERS_PATH, ANSWER_COLUMNS)


@st.cache_data
def discover_exam_files() -> list[dict]:
    records = []
    seen = set()

    for base in DATA_DIR_CANDIDATES:
        if not base.exists():
            continue

        for path in sorted(base.glob("module_*_exam_*.csv")):
            resolved = path.resolve()
            if resolved in seen or not csv_has_any_content(path):
                continue
            seen.add(resolved)

            m = re.search(r"module_(\d+)_exam_(\d+)_(\d+)", path.stem, re.IGNORECASE)
            if m:
                module_no = int(m.group(1))
                q_start = int(m.group(2))
                q_end = int(m.group(3))
                label = f"Module {module_no:02d} ({q_start}-{q_end})"
                sort_key = module_no
            else:
                label = path.stem
                sort_key = 9999

            records.append({
                "bank_id": path.stem,
                "bank_label": label,
                "path": str(path),
                "sort_key": sort_key,
            })

        fallback = base / "questions.csv"
        if fallback.exists() and fallback.resolve() not in seen and csv_has_any_content(fallback):
            seen.add(fallback.resolve())
            records.append({
                "bank_id": fallback.stem,
                "bank_label": "questions.csv",
                "path": str(fallback),
                "sort_key": 10000,
            })

    records = sorted(records, key=lambda x: (x["sort_key"], x["bank_label"]))
    return records


@st.cache_data
def load_questions() -> tuple[pd.DataFrame, pd.DataFrame]:
    exam_files = discover_exam_files()
    if not exam_files:
        return pd.DataFrame(), pd.DataFrame()

    frames = []
    bank_rows = []

    for item in exam_files:
        path = Path(item["path"])
        try:
            df = pd.read_csv(path).fillna("")
        except Exception:
            continue

        expected = [
            "question_id",
            "question_type",
            "stem",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "option_e",
            "option_f",
            "correct_answer",
            "explanation",
            "topic",
        ]
        for col in expected:
            if col not in df.columns:
                df[col] = ""

        if "question_id" in df.columns:
            df["question_id"] = pd.to_numeric(df["question_id"], errors="coerce")
        else:
            df["question_id"] = range(1, len(df) + 1)

        df["question_type"] = df["question_type"].replace("", "single")
        df["bank_id"] = item["bank_id"]
        df["bank_label"] = item["bank_label"]
        df["source_file"] = path.name
        df["source_dir"] = str(path.parent)
        df["question_uid"] = df["bank_id"].astype(str) + ":" + df["question_id"].fillna(0).astype(int).astype(str)
        df = df.sort_values("question_id").reset_index(drop=True)

        frames.append(df)
        bank_rows.append({
            "bank_id": item["bank_id"],
            "bank_label": item["bank_label"],
            "source_file": path.name,
            "question_count": int(len(df)),
        })

    if not frames:
        return pd.DataFrame(), pd.DataFrame()

    all_df = pd.concat(frames, ignore_index=True)
    bank_df = pd.DataFrame(bank_rows).sort_values(["bank_label", "source_file"]).reset_index(drop=True)
    return all_df, bank_df


def load_attempt_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_history_files()
    try:
        summary = pd.read_csv(ATTEMPTS_SUMMARY_PATH).fillna("")
    except Exception:
        summary = pd.DataFrame(columns=SUMMARY_COLUMNS)
    try:
        answers = pd.read_csv(ATTEMPT_ANSWERS_PATH).fillna("")
    except Exception:
        answers = pd.DataFrame(columns=ANSWER_COLUMNS)
    return summary, answers


def option_map(row) -> dict:
    options = {}
    for key, label in OPTION_COLUMN_LABELS:
        value = normalize_text(row.get(key, ""))
        if value:
            options[label] = value
    return options


def is_matching_question(row) -> bool:
    q_type = normalize_text(row.get("question_type", "")).lower()
    stem = normalize_text(row.get("stem", "")).lower()
    return ("match" in q_type) or ("matching" in q_type) or ("match the corresponding" in stem)


def is_multi_select_question(row) -> bool:
    if is_matching_question(row):
        return False
    q_type = normalize_text(row.get("question_type", "")).lower()
    answer = normalize_answer(row.get("correct_answer", ""))
    return ("," in answer) or (q_type in {"multi", "multiple", "multiple_select", "multiple_choice_multiple"})


def init_state():
    defaults = {
        "started": False,
        "submitted": False,
        "current_idx": 0,
        "answers": {},
        "current_df": None,
        "mode": "Selected Bank",
        "submit_confirm": False,
        "attempt_saved": False,
        "last_attempt_id": "",
        "topic_filter_label": "All topics",
        "review_mode": False,
        "bank_label": "All Exams",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset_exam(selected_df: pd.DataFrame, mode_label: str, topic_filter_label: str, bank_label: str):
    st.session_state.started = True
    st.session_state.submitted = False
    st.session_state.current_idx = 0
    st.session_state.answers = {}
    st.session_state.current_df = selected_df.reset_index(drop=True).to_dict("records")
    st.session_state.mode = mode_label
    st.session_state.submit_confirm = False
    st.session_state.attempt_saved = False
    st.session_state.last_attempt_id = ""
    st.session_state.topic_filter_label = topic_filter_label
    st.session_state.review_mode = False
    st.session_state.bank_label = bank_label


def reset_review(selected_df: pd.DataFrame, topic_filter_label: str, bank_label: str):
    st.session_state.started = True
    st.session_state.submitted = False
    st.session_state.current_idx = 0
    st.session_state.answers = {}
    st.session_state.current_df = selected_df.reset_index(drop=True).to_dict("records")
    st.session_state.mode = "Review Explanations"
    st.session_state.submit_confirm = False
    st.session_state.attempt_saved = False
    st.session_state.last_attempt_id = ""
    st.session_state.topic_filter_label = topic_filter_label
    st.session_state.review_mode = True
    st.session_state.bank_label = bank_label


def get_current_df():
    if st.session_state.current_df is None:
        return None
    return pd.DataFrame(st.session_state.current_df)


def answered_count() -> int:
    return sum(1 for v in st.session_state.answers.values() if normalize_text(v))


def save_attempt(results_df: pd.DataFrame, mode_label: str, topic_filter_label: str, bank_label: str):
    ensure_history_files()
    attempt_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    timestamp = datetime.now().isoformat(timespec="seconds")

    summary_row = pd.DataFrame([
        {
            "attempt_id": attempt_id,
            "timestamp": timestamp,
            "mode": mode_label,
            "bank_label": bank_label,
            "topic_filter": topic_filter_label,
            "question_count": int(len(results_df)),
            "answered_count": int((results_df["user_answer"].astype(str).str.strip() != "").sum()),
            "score": int(results_df["is_correct"].sum()),
            "percentage": round((results_df["is_correct"].sum() / len(results_df)) * 100, 1) if len(results_df) else 0.0,
        }
    ])

    answer_rows = results_df.copy()
    answer_rows["attempt_id"] = attempt_id
    answer_rows["timestamp"] = timestamp
    answer_rows["mode"] = mode_label
    answer_rows["bank_label"] = bank_label
    answer_rows = answer_rows[ANSWER_COLUMNS]

    old_summary = pd.read_csv(ATTEMPTS_SUMMARY_PATH).fillna("")
    old_answers = pd.read_csv(ATTEMPT_ANSWERS_PATH).fillna("")

    pd.concat([old_summary, summary_row], ignore_index=True).to_csv(ATTEMPTS_SUMMARY_PATH, index=False)
    pd.concat([old_answers, answer_rows], ignore_index=True).to_csv(ATTEMPT_ANSWERS_PATH, index=False)
    return attempt_id


def build_wrong_only_df(filtered_bank_df: pd.DataFrame, answers_history: pd.DataFrame):
    if filtered_bank_df.empty or answers_history.empty:
        return pd.DataFrame()

    if "question_uid" in answers_history.columns and "question_uid" in filtered_bank_df.columns:
        wrong_keys = (
            answers_history[answers_history["is_correct"].astype(str).str.lower().isin(["false", "0"])]
            ["question_uid"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        if wrong_keys:
            return filtered_bank_df[filtered_bank_df["question_uid"].astype(str).isin(wrong_keys)].copy().reset_index(drop=True)

    wrong_ids = (
        answers_history[answers_history["is_correct"].astype(str).str.lower().isin(["false", "0"])]
        ["question_id"]
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    if not wrong_ids:
        return pd.DataFrame()
    return filtered_bank_df[filtered_bank_df["question_id"].astype(int).isin(wrong_ids)].copy().reset_index(drop=True)


def apply_topic_filter(df: pd.DataFrame, topics: list[str]):
    if not topics:
        return df.copy().reset_index(drop=True), "All topics"
    filtered = df[df["topic"].astype(str).isin(topics)].copy().reset_index(drop=True)
    return filtered, ", ".join(topics)


def filter_bank(all_df: pd.DataFrame, bank_choice: str):
    if bank_choice == "All Exams (Combined)":
        return all_df.copy().reset_index(drop=True), bank_choice
    filtered = all_df[all_df["bank_label"].astype(str) == bank_choice].copy().reset_index(drop=True)
    return filtered, bank_choice


def render_question_media(row):
    for col in IMAGE_COLUMN_CANDIDATES:
        value = normalize_text(row.get(col, ""))
        if not value:
            continue

        if value.startswith("http://") or value.startswith("https://"):
            st.image(value, use_container_width=True)
            return

        p = Path(value)
        if not p.is_absolute():
            source_dir = normalize_text(row.get("source_dir", ""))
            if source_dir:
                p = Path(source_dir) / value
            else:
                p = SCRIPT_DIR / value

        if p.exists():
            st.image(str(p), use_container_width=True)
        else:
            st.warning(f"Image referenced but not found: {value}")
        return


def render_dashboard(summary_df: pd.DataFrame, answers_df: pd.DataFrame, bank_df: pd.DataFrame):
    st.subheader("Dashboard")

    c1, c2, c3 = st.columns(3)
    c1.metric("Files Loaded", f"{len(bank_df)}")
    c2.metric("Questions Loaded", f"{int(bank_df['question_count'].sum()) if not bank_df.empty else 0}")
    c3.metric("Saved Attempts", f"{len(summary_df)}")

    if not bank_df.empty:
        with st.expander("Loaded Exams", expanded=True):
            st.dataframe(bank_df[["bank_label", "source_file", "question_count"]], use_container_width=True, hide_index=True)

    if summary_df.empty:
        st.info("No saved attempts yet.")
        return

    avg_pct = pd.to_numeric(summary_df["percentage"], errors="coerce").dropna()
    best_pct = avg_pct.max() if not avg_pct.empty else 0.0
    last_pct = pd.to_numeric(summary_df.iloc[-1:].get("percentage"), errors="coerce").fillna(0).iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Average", f"{avg_pct.mean():.1f}%" if not avg_pct.empty else "0.0%")
    c2.metric("Best", f"{best_pct:.1f}%")
    c3.metric("Latest", f"{last_pct:.1f}%")

    if not answers_df.empty:
        wrong_df = answers_df[answers_df["is_correct"].astype(str).str.lower().isin(["false", "0"])].copy()
        if not wrong_df.empty:
            topic_counts = (
                wrong_df.assign(topic=wrong_df["topic"].replace("", "Unknown"))
                .groupby("topic")
                .size()
                .reset_index(name="wrong_count")
                .sort_values(["wrong_count", "topic"], ascending=[False, True])
            )
            with st.expander("Weak Topics Overview", expanded=False):
                st.dataframe(topic_counts, use_container_width=True, hide_index=True)

    recent = summary_df.tail(10).copy()
    with st.expander("Recent Attempts", expanded=False):
        st.dataframe(
            recent[["timestamp", "bank_label", "mode", "topic_filter", "question_count", "score", "percentage"]],
            use_container_width=True,
            hide_index=True,
        )


init_state()
all_df, bank_df = load_questions()
summary_df, answers_df = load_attempt_history()

st.title("Zamala QBank Pro")

if all_df.empty:
    st.error("No question CSV files were found. Put the six module CSV files next to main.py or inside a data folder.")
    st.stop()

bank_choices = ["All Exams (Combined)"] + bank_df["bank_label"].tolist()
all_topics = sorted([t for t in all_df["topic"].astype(str).fillna("").unique().tolist() if t.strip()])

with st.sidebar:
    st.header("Exam Controls")
    current_len = len(get_current_df()) if get_current_df() is not None else len(all_df)
    st.write(f"Loaded **{len(all_df)}** questions")
    st.write(f"Answered: **{answered_count()}/{current_len}**")

    bank_choice = st.selectbox("Exam Bank", bank_choices)
    mode_choice = st.selectbox(
        "Mode",
        [
            "Selected Bank",
            "Random Mock (100)",
            "Mini Test (20)",
            "Wrong Answers Only",
            "Review Explanations",
        ],
    )

    selected_topics = st.multiselect("Filter by topic", all_topics)

    if st.button("Start / Restart", use_container_width=True):
        bank_filtered_df, current_bank_label = filter_bank(all_df, bank_choice)
        filtered_df, topic_filter_label = apply_topic_filter(bank_filtered_df, selected_topics)

        if filtered_df.empty:
            st.warning("No questions match the selected exam bank / topic filter.")
        elif mode_choice == "Selected Bank":
            reset_exam(filtered_df, mode_choice, topic_filter_label, current_bank_label)
        elif mode_choice == "Random Mock (100)":
            n = min(100, len(filtered_df))
            reset_exam(filtered_df.sample(n=n).reset_index(drop=True), mode_choice, topic_filter_label, current_bank_label)
        elif mode_choice == "Mini Test (20)":
            n = min(20, len(filtered_df))
            reset_exam(filtered_df.sample(n=n).reset_index(drop=True), mode_choice, topic_filter_label, current_bank_label)
        elif mode_choice == "Wrong Answers Only":
            wrong_df = build_wrong_only_df(filtered_df, answers_df)
            if wrong_df.empty:
                st.warning("No previous wrong answers found for the selected bank / filter.")
            else:
                reset_exam(wrong_df, mode_choice, topic_filter_label, current_bank_label)
        else:
            reset_review(filtered_df, topic_filter_label, current_bank_label)

    current_df = get_current_df()
    if current_df is not None and not current_df.empty and st.session_state.started:
        q_labels = [
            f"{i + 1}. Q{int(qid)} — {bank}"
            for i, (qid, bank) in enumerate(zip(current_df["question_id"].tolist(), current_df["bank_label"].tolist()))
        ]
        selected_jump = st.selectbox(
            "Jump to question",
            q_labels,
            index=min(st.session_state.current_idx, len(q_labels) - 1),
        )
        selected_idx = q_labels.index(selected_jump)
        if selected_idx != st.session_state.current_idx:
            st.session_state.current_idx = selected_idx
            st.rerun()

    st.divider()
    st.subheader("History")
    if not summary_df.empty:
        st.write(f"Attempts: **{len(summary_df)}**")
        latest = summary_df.iloc[-1]
        st.write(f"Latest: **{latest.get('score', '')}/{latest.get('question_count', '')}**")
        avg_pct = pd.to_numeric(summary_df["percentage"], errors="coerce").dropna()
        if not avg_pct.empty:
            st.write(f"Average: **{avg_pct.mean():.1f}%**")
    else:
        st.caption("No saved attempts yet.")

current_df = get_current_df()

if not st.session_state.started or current_df is None or current_df.empty:
    render_dashboard(summary_df, answers_df, bank_df)
    st.info("Choose an exam bank and a mode from the sidebar, then press Start / Restart.")
    preview_cols = [c for c in ["bank_label", "question_id", "stem", "topic"] if c in all_df.columns]
    st.dataframe(all_df[preview_cols], use_container_width=True, hide_index=True)
    st.stop()

if st.session_state.current_idx >= len(current_df):
    st.session_state.current_idx = len(current_df) - 1
if st.session_state.current_idx < 0:
    st.session_state.current_idx = 0

idx = st.session_state.current_idx
row = current_df.iloc[idx]
q_id = int(row["question_id"])
saved_answer = st.session_state.answers.get(idx, "")

st.progress((idx + 1) / len(current_df))
st.subheader(f"Question {idx + 1} of {len(current_df)}")
meta = []
if normalize_text(row.get("bank_label", "")):
    meta.append(f"Exam: {row['bank_label']}")
if normalize_text(row.get("topic", "")):
    meta.append(f"Topic: {row['topic']}")
if q_id:
    meta.append(f"Question ID: {q_id}")
if meta:
    st.caption(" | ".join(meta))

st.write(row["stem"])
render_question_media(row)

if st.session_state.review_mode:
    options = option_map(row)
    if options:
        st.markdown("**Options**")
        for label, text in options.items():
            st.write(f"{label}) {text}")
    st.success(f"Correct answer: {normalize_answer(row.get('correct_answer', ''))}")
    if normalize_text(row.get("explanation", "")):
        st.info(row["explanation"])
else:
    if is_matching_question(row):
        st.info("Matching question: enter your answer like B,A,C,D")
        typed = st.text_input(
            "Your answer",
            value=saved_answer,
            key=f"txt_{idx}",
            placeholder="Example: B,A,C,D",
        )
        st.session_state.answers[idx] = normalize_answer(typed)
    elif is_multi_select_question(row):
        options = option_map(row)
        labels = list(options.keys())
        default_values = split_answer_letters(saved_answer)
        selected = st.multiselect(
            "Choose all correct answers:",
            options=labels,
            default=[x for x in default_values if x in labels],
            format_func=lambda x: f"{x}) {options[x]}",
            key=f"multi_{idx}",
        )
        st.session_state.answers[idx] = ",".join(selected)
    else:
        options = option_map(row)
        labels = list(options.keys())
        display_options = [f"{label}) {options[label]}" for label in labels]

        default_index = None
        if saved_answer in labels:
            default_index = labels.index(saved_answer)

        choice = st.radio(
            "Choose one answer:",
            options=display_options,
            index=default_index,
            key=f"q_{idx}",
        )

        if choice is not None:
            selected_label = choice.split(")", 1)[0].strip()
            st.session_state.answers[idx] = selected_label
        elif idx not in st.session_state.answers:
            st.session_state.answers[idx] = ""

nav1, nav2, nav3 = st.columns(3)
with nav1:
    if st.button("Previous", disabled=idx == 0, use_container_width=True):
        st.session_state.current_idx -= 1
        st.rerun()
with nav2:
    if st.button("Next", disabled=idx == len(current_df) - 1, use_container_width=True):
        st.session_state.current_idx += 1
        st.rerun()
with nav3:
    if not st.session_state.review_mode:
        if st.button("Submit Exam", use_container_width=True):
            unanswered = len(current_df) - answered_count()
            if unanswered > 0 and not st.session_state.submit_confirm:
                st.session_state.submit_confirm = True
            else:
                st.session_state.submitted = True
                st.session_state.submit_confirm = False
            st.rerun()

if not st.session_state.review_mode:
    st.write(f"Answered: **{answered_count()}/{len(current_df)}**")
else:
    st.write(f"Study item: **{idx + 1}/{len(current_df)}**")

if st.session_state.submit_confirm and not st.session_state.submitted and not st.session_state.review_mode:
    unanswered = len(current_df) - answered_count()
    st.warning(f"You still have **{unanswered}** unanswered questions.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Submit Anyway", use_container_width=True):
            st.session_state.submitted = True
            st.session_state.submit_confirm = False
            st.rerun()
    with c2:
        if st.button("Continue Exam", use_container_width=True):
            st.session_state.submit_confirm = False
            st.rerun()

if st.session_state.submitted and not st.session_state.review_mode:
    results = []
    for i, q in current_df.iterrows():
        user_answer = normalize_answer(st.session_state.answers.get(i, ""))
        correct = normalize_answer(q.get("correct_answer", ""))
        ordered = is_matching_question(q)
        is_correct = compare_answers(user_answer, correct, ordered=ordered)
        results.append(
            {
                "question_uid": q.get("question_uid", ""),
                "question_id": int(q["question_id"]) if pd.notna(q["question_id"]) else i + 1,
                "topic": q.get("topic", ""),
                "user_answer": user_answer,
                "correct_answer": correct,
                "is_correct": is_correct,
                "stem": q.get("stem", ""),
                "explanation": q.get("explanation", ""),
                "bank_label": q.get("bank_label", st.session_state.bank_label),
            }
        )

    results_df = pd.DataFrame(results)
    score = int(results_df["is_correct"].sum())
    total = int(len(results_df))
    pct = round((score / total) * 100, 1) if total else 0.0
    unanswered = int((results_df["user_answer"].astype(str).str.strip() == "").sum())

    if not st.session_state.attempt_saved:
        attempt_id = save_attempt(
            results_df,
            st.session_state.mode,
            st.session_state.topic_filter_label,
            st.session_state.bank_label,
        )
        st.session_state.attempt_saved = True
        st.session_state.last_attempt_id = attempt_id

    st.divider()
    st.header("Result")
    m1, m2, m3 = st.columns(3)
    m1.metric("Score", f"{score}/{total}")
    m2.metric("Percentage", f"{pct}%")
    m3.metric("Unanswered", f"{unanswered}")
    st.caption(f"Saved attempt ID: {st.session_state.last_attempt_id}")
    st.caption(f"Exam bank: {st.session_state.bank_label}")
    st.caption(f"Filter used: {st.session_state.topic_filter_label}")

    if not results_df.empty:
        download_df = results_df[[
            "bank_label",
            "question_id",
            "topic",
            "user_answer",
            "correct_answer",
            "is_correct",
            "stem",
            "explanation",
        ]].copy()
        st.download_button(
            "Download Result CSV",
            data=download_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"zamala_results_{st.session_state.last_attempt_id}.csv",
            mime="text/csv",
        )

    wrong_df = results_df[~results_df["is_correct"]].copy()
    if not wrong_df.empty and "topic" in wrong_df.columns:
        topic_counts = (
            wrong_df.assign(topic=wrong_df["topic"].replace("", "Unknown"))
            .groupby("topic")
            .size()
            .reset_index(name="wrong_count")
            .sort_values(["wrong_count", "topic"], ascending=[False, True])
        )
        st.subheader("Weak Topics")
        st.dataframe(topic_counts, use_container_width=True, hide_index=True)

    if wrong_df.empty:
        st.success("Excellent. No wrong answers.")
    else:
        st.subheader("Wrong Answers Review")
        for _, item in wrong_df.iterrows():
            st.markdown(f"### {item['bank_label']} — Q{int(item['question_id'])}")
            st.write(item["stem"])
            st.write(f"**Your answer:** {item['user_answer'] or 'No answer'}")
            st.write(f"**Correct answer:** {item['correct_answer']}")
            if normalize_text(item.get("topic", "")):
                st.write(f"**Topic:** {item['topic']}")
            if normalize_text(item.get("explanation", "")):
                st.write(f"**Explanation:** {item['explanation']}")
            st.divider()
