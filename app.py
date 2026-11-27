import hashlib
import io
from google.oauth2.service_account import Credentials
import gspread
from gtts import gTTS
import pandas as pd
import streamlit as st

# Name deines Google Sheets
SPREADSHEET_NAME = "Vokabeltrainer_DB"

SPRACHEN = {
    "Englisch": "en",
    "Spanisch": "es",
    "Französisch": "fr",
    "Italienisch": "it",
    "Portugiesisch": "pt",
    "Niederländisch": "nl",
    "Deutsch": "de",
}


# --- GOOGLE SHEETS VERBINDUNG ---
@st.cache_resource
def get_sheets():
    """Verbindet sich mit Google Sheets über Streamlit Secrets."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    workbook = client.open(SPREADSHEET_NAME)
    return workbook.worksheet("users"), workbook.worksheet("vocab")


# --- DATENBANK-FUNKTIONEN (GOOGLE SHEETS) ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def register_user(username, password):
    users_ws, vocab_ws = get_sheets()
    users = users_ws.get_all_records()

    # Prüfen, ob Benutzername existiert
    if any(str(u["username"]).lower() == username.lower() for u in users):
        return False

    new_id = max([int(u["id"]) for u in users], default=0) + 1
    users_ws.append_row([new_id, username, hash_password(password)])

    # Start-Vokabeln anlegen
    vocab_records = vocab_ws.get_all_records()
    next_vocab_id = max([int(v["id"]) for v in vocab_records], default=0) + 1

    beispiele = [
        [next_vocab_id, new_id, "to improve", "verbessern", 1],
        [next_vocab_id + 1, new_id, "sustainable", "nachhaltig", 1],
        [next_vocab_id + 2, new_id, "opportunity", "Gelegenheit", 1],
    ]
    vocab_ws.append_rows(beispiele)
    return True


def login_user(username, password):
    users_ws, _ = get_sheets()
    users = users_ws.get_all_records()
    pw_hash = hash_password(password)

    for u in users:
        if str(u["username"]) == username and str(u["password_hash"]) == pw_hash:
            return int(u["id"])
    return None


def get_user_vocab_df(user_id):
    """Lädt alle Vokabeln eines Nutzers inklusive Zeilennummer im Sheet."""
    _, vocab_ws = get_sheets()
    records = vocab_ws.get_all_records()
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    # Zeilennummer im Google Sheet merken (Header ist Zeile 1, Daten starten ab Zeile 2)
    df["sheet_row"] = df.index + 2
    df["user_id"] = pd.to_numeric(df["user_id"], errors="coerce")
    df["box"] = pd.to_numeric(df["box"], errors="coerce").fillna(1).astype(int)

    return df[df["user_id"] == user_id]


def get_next_card(user_id):
    df = get_user_vocab_df(user_id)
    if df.empty:
        return None

    # Niedrigste Box zuerst, innerhalb dieser Box zufällig wählen
    min_box = df["box"].min()
    candidates = df[df["box"] == min_box]
    chosen = candidates.sample(n=1).iloc[0]

    return (
        int(chosen["sheet_row"]),
        str(chosen["fremdsprache"]),
        str(chosen["deutsch"]),
        int(chosen["box"]),
    )


def update_card_box(sheet_row, new_box):
    _, vocab_ws = get_sheets()
    # Spalte 5 (E) ist 'box'
    vocab_ws.update_cell(sheet_row, 5, new_box)


def add_vocab(user_id, fremd, deutsch):
    _, vocab_ws = get_sheets()
    records = vocab_ws.get_all_records()
    next_id = max([int(v["id"]) for v in records], default=0) + 1
    vocab_ws.append_row([next_id, user_id, fremd, deutsch, 1])


def add_vocab_bulk(user_id, paare):
    _, vocab_ws = get_sheets()
    records = vocab_ws.get_all_records()
    next_id = max([int(v["id"]) for v in records], default=0) + 1

    rows = []
    for idx, (f, d) in enumerate(paare):
        rows.append([next_id + idx, user_id, f, d, 1])

    vocab_ws.append_rows(rows)


def get_all_vocab(user_id):
    df = get_user_vocab_df(user_id)
    if df.empty:
        return []
    df = df.sort_values(by="box", ascending=True)
    return list(zip(df["fremdsprache"], df["deutsch"], df["box"]))


# --- AUDIO-FUNKTION (TTS) ---
@st.cache_data(show_spinner=False)
def text_zu_audio(text, lang_code):
    tts = gTTS(text=text, lang=lang_code)
    audio_buffer = io.BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return audio_buffer.read()


# --- WEB-OBERFLÄCHE (STREAMLIT) ---
st.set_page_config(page_title="Vokabel-Plattform", page_icon="📚", layout="centered")

if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = ""
if "current_card" not in st.session_state:
    st.session_state.current_card = None
if "feedback" not in st.session_state:
    st.session_state.feedback = None

st.title("📚 Vokabel-Lernplattform")

# 1. ANSICHT: LOGIN / REGISTRIERUNG
if st.session_state.user_id is None:
    tab1, tab2 = st.tabs(["Anmelden", "Registrieren"])

    with tab1:
        with st.form("login_form"):
            user_in = st.text_input("Benutzername")
            pass_in = st.text_input("Passwort", type="password")
            if st.form_submit_button("Einloggen"):
                with st.spinner("Verbinde mit Datenbank..."):
                    uid = login_user(user_in, pass_in)
                if uid:
                    st.session_state.user_id = uid
                    st.session_state.username = user_in
                    st.session_state.current_card = get_next_card(uid)
                    st.rerun()
                else:
                    st.error("Benutzername oder Passwort falsch.")

    with tab2:
        with st.form("register_form"):
            new_user = st.text_input("Neuer Benutzername")
            new_pass = st.text_input("Neues Passwort", type="password")
            if st.form_submit_button("Konto erstellen"):
                if new_user and new_pass:
                    with st.spinner("Erstelle Konto..."):
                        erfolg = register_user(new_user, new_pass)
                    if erfolg:
                        st.success("Konto erstellt! Du kannst dich jetzt anmelden.")
                    else:
                        st.error("Dieser Benutzername ist bereits vergeben.")
                else:
                    st.warning("Bitte beide Felder ausfüllen.")

# 2. ANSICHT: EINGELOGGTER BEREICH
else:
    col1, col2, col3 = st.columns([3, 2, 1])
    col1.caption(f"Eingeloggt als **{st.session_state.username}**")
    gewaehlte_sprache = col2.selectbox(
        "Aussprache",
        options=list(SPRACHEN.keys()),
        label_visibility="collapsed",
    )
    if col3.button("Logout"):
        st.session_state.user_id = None
        st.session_state.current_card = None
        st.session_state.feedback = None
        st.rerun()

    tab_lernen, tab_neu, tab_csv, tab_stats = st.tabs([
        "🧠 Lernen",
        "➕ Einzeln hinzufügen",
        "📂 CSV-Import",
        "📊 Statistik & Liste",
    ])

    # TAB 1: LERNMODUS MIT AUDIO
    with tab_lernen:
        card = st.session_state.current_card
        if not card:
            st.info(
                "Keine Vokabeln vorhanden. Füge Wörter hinzu oder importiere eine CSV-Datei!"
            )
        else:
            sheet_row, fremd, deutsch, box = card
            st.progress(box / 5, text=f"Karteikasten: Box {box} von 5")

            st.markdown(f"### Was heißt: **{fremd}**?")

            try:
                audio_bytes = text_zu_audio(fremd, SPRACHEN[gewaehlte_sprache])
                st.audio(audio_bytes, format="audio/mp3")
            except Exception:
                st.caption("⚠️ Audio-Ausgabe momentan nicht verfügbar.")

            with st.form("quiz_form", clear_on_submit=True):
                antwort = st.text_input("Deine Übersetzung:")
                submitted = st.form_submit_button("Prüfen")

                if submitted and antwort:
                    if antwort.strip().lower() == deutsch.strip().lower():
                        new_box = min(5, box + 1)
                        update_card_box(sheet_row, new_box)
                        st.session_state.feedback = (
                            "success",
                            f"✅ Richtig! '{fremd}' = '{deutsch}' (Jetzt in Box {new_box})",
                        )
                    else:
                        update_card_box(sheet_row, 1)
                        st.session_state.feedback = (
                            "error",
                            f"❌ Falsch. Richtig wäre '{deutsch}' gewesen. Zurück in Box 1.",
                        )

                    st.session_state.current_card = get_next_card(st.session_state.user_id)
                    st.rerun()

            if st.session_state.feedback:
                typ, msg = st.session_state.feedback
                if typ == "success":
                    st.success(msg)
                else:
                    st.error(msg)

    # TAB 2: EINZELNE VOKABEL
    with tab_neu:
        with st.form("add_form", clear_on_submit=True):
            fremd_neu = st.text_input("Fremdsprache")
            deutsch_neu = st.text_input("Deutsche Übersetzung")
            if st.form_submit_button("Speichern"):
                if fremd_neu and deutsch_neu:
                    with st.spinner("Speichere in Google Sheets..."):
                        add_vocab(
                            st.session_state.user_id,
                            fremd_neu.strip(),
                            deutsch_neu.strip(),
                        )
                    if st.session_state.current_card is None:
                        st.session_state.current_card = get_next_card(
                            st.session_state.user_id
                        )
                    st.success(f"'{fremd_neu} - {deutsch_neu}' gespeichert!")
                else:
                    st.warning("Bitte beide Felder ausfüllen.")

    # TAB 3: CSV-IMPORT
    with tab_csv:
        st.subheader("Vokabelliste per CSV hochladen")
        st.markdown(
            "Die CSV-Datei benötigt zwei Spalten: **1. Spalte = Fremdsprache**, **2. Spalte = Deutsch**."
        )

        beispiel_csv = "Fremdsprache;Deutsch\napple;Apfel\nbook;Buch\nto achieve;erreichen"
        st.download_button(
            label="📥 Beispiel-CSV herunterladen",
            data=beispiel_csv.encode("utf-8"),
            file_name="vokabel_vorlage.csv",
            mime="text/csv",
        )

        uploaded_file = st.file_uploader("CSV-Datei auswählen", type=["csv"])
        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file, sep=None, engine="python")
                if df.shape[1] < 2:
                    st.error("Die Datei muss mindestens zwei Spalten enthalten.")
                else:
                    df_clean = df.iloc[:, :2].dropna()
                    df_clean.columns = ["Fremdsprache", "Deutsch"]
                    st.dataframe(df_clean.head(10), use_container_width=True, hide_index=True)

                    if st.button(f"{len(df_clean)} Vokabeln jetzt importieren"):
                        paare = [
                            (str(row["Fremdsprache"]).strip(), str(row["Deutsch"]).strip())
                            for _, row in df_clean.iterrows()
                        ]
                        with st.spinner("Importiere Vokabeln..."):
                            add_vocab_bulk(st.session_state.user_id, paare)
                        if st.session_state.current_card is None:
                            st.session_state.current_card = get_next_card(
                                st.session_state.user_id
                            )
                        st.success(f"✅ {len(paare)} Vokabeln erfolgreich importiert!")
            except Exception as e:
                st.error(f"Fehler beim Lesen der CSV-Datei: {e}")

    # TAB 4: STATISTIK
    with tab_stats:
        alle = get_all_vocab(st.session_state.user_id)
        if not alle:
            st.write("Noch keine Daten vorhanden.")
        else:
            gesamt = len(alle)
            gemeistert = sum(1 for v in alle if v[2] == 5)
            c1, c2 = st.columns(2)
            c1.metric("Vokabeln gesamt", gesamt)
            c2.metric("Gemeistert (Box 5)", gemeistert)

            st.divider()
            st.subheader("Alle Vokabeln")
            daten_tabelle = [
                {"Fremdsprache": v[0], "Deutsch": v[1], "Box": f"{v[2]} / 5"}
                for v in alle
            ]
            st.dataframe(daten_tabelle, use_container_width=True, hide_index=True)
