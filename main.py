import os
import json
import sqlite3
import streamlit as st
from typing import TypedDict
from dotenv import load_dotenv
from groq import Groq
from langgraph.graph import StateGraph, END

# 🔐 Environment
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
DB_FILE = "user.db"

# 🧠 LangGraph state
class GraphState(TypedDict):
    query: str
    result: str

# 🧱 DB Initialization
def create_user_table():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            history TEXT
        )
    """)
    conn.commit()
    conn.close()

# 🔐 User management
def signup_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO users (username, password, history) VALUES (?, ?, ?)",
                (username, password, "[]"))
    conn.commit()
    conn.close()

def validate_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row and row[0] == password
 
def get_user_history(username):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT history FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return json.loads(row[0]) if row and row[0] else []

def update_user_history(username, history):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("UPDATE users SET history=? WHERE username=?", (json.dumps(history), username))
    conn.commit()
    conn.close()

# 🔍 Islamic search
def count_tokens(text):
    return len(text.split())  # Approximation for tokens


def groq_shamila_search(query):
    # 1️⃣ Check if question alone is too long
    if count_tokens(query) > 300:
        return "Your question is too long. Please ask in fewer words."

    # 2️⃣ Load history (guest or logged-in)
    if st.session_state.authenticated:
        username = st.session_state.username
        history = get_user_history(username)
    else:
        history = st.session_state.get("conversation_history", [])

    # 3️⃣ Estimate total tokens (history + current question)
    def total_tokens(hist, q):
        return sum(count_tokens(hq) + count_tokens(ha) for hq, ha in hist) + count_tokens(q)

    trimmed = False
    max_allowed_tokens = 1500  # Safe limit for this model
    tokens_now = total_tokens(history, query)

    # 4️⃣ Trim oldest history if needed
    while tokens_now > max_allowed_tokens and history:
        history.pop(0)
        tokens_now = total_tokens(history, query)
        trimmed = True

    # 5️⃣ Still too long after trimming? Reject.
    if tokens_now > max_allowed_tokens:
        return "Your question and conversation history exceed the allowed limit. Please ask a shorter question."

    # 6️⃣ Inform user politely if trimming happened
    if trimmed:
        st.info("Some of your previous conversation was trimmed to keep within limits.")

    # 7️⃣ Prepare messages
    messages = [{
        "role": "system",
        "content": (
            "You are an Islamic scholar answering ONLY from authentic Islamic books from Maktaba Shamila (shamilaurdu.com). "
            "Provide references from books where possible. If question isn't Islamic, say: "
            "'I'm sorry, I can only assist with Islamic-related questions.'"
        )
    }]
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": query})

    # 8️⃣ Streaming answer properly
    response = client.chat.completions.create(
        model="compound-beta-mini",
        messages=messages,
        stream=True,
        search_settings={"include_domains": ["shamilaurdu.com"]}
    )

    answer_chunks = []
    for chunk in response:
        if hasattr(chunk.choices[0].delta, "content") and chunk.choices[0].delta.content:
            answer_chunks.append(chunk.choices[0].delta.content)

    answer = "".join(answer_chunks)

    # 9️⃣ Update history
    history.append((query, answer))
    if st.session_state.authenticated:
        update_user_history(username, history)
        st.session_state.conversation_history = history
    else:
        st.session_state.conversation_history = history

    return answer


# 🧩 LangGraph wrapper
def search_wrapper(state: GraphState, config) -> GraphState:
    answer = groq_shamila_search(state["query"])
    return {"query": state["query"], "result": answer}

flow = StateGraph(GraphState)
flow.add_node("groq_search", search_wrapper)
flow.add_edge("groq_search", END)
flow.set_entry_point("groq_search")
graph = flow.compile()

# 🧭 UI components
def login_ui():
    st.subheader("🔐 Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if validate_user(username, password):
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.conversation_history = get_user_history(username)
            st.success(f"Welcome back, {username}!")
        else:
            st.error("Invalid credentials.")

def signup_ui():
    st.subheader("📝 Sign Up")
    username = st.text_input("Choose Username")
    password = st.text_input("Choose Password", type="password")
    if st.button("Create Account"):
        try:
            signup_user(username, password)
            st.success("Account created. Please log in.")
        except:
            st.error("Username already exists.")

def chat_ui():
    st.title("🕋 Islamic Chatbot")

    # 🧠 Init guest history
    if "conversation_history" not in st.session_state:
        st.session_state.conversation_history = []

    # 💬 Conversation display
    st.markdown("## 💬 Conversation")
    for q, a in st.session_state.conversation_history:
        st.markdown(f"**You:** {q}")
        st.markdown(f"**Shamila Urdu:** {a}")
        st.markdown("---")

    # 📜 Scroll to bottom
    st.markdown("<a name='bottom'></a>", unsafe_allow_html=True)
    st.markdown("""
        <script>
            document.getElementsByName('bottom')[0].scrollIntoView({ behavior: 'smooth' });
        </script>
    """, unsafe_allow_html=True)

    # ✍️ Input
    prompt = st.chat_input("Ask your question about Islam...")
    if prompt:
        if count_tokens(prompt) > 300:
            st.warning("Your question is too long. Please ask in fewer words.")
        else:
        # Show placeholder while thinking
            st.markdown("🕊️ MIRC is writing...", unsafe_allow_html=True)
            with st.spinner("Searching..."):
                result = graph.invoke({"query": prompt, "result": ""})
        
        # Rerun will automatically refresh with full answer
            st.rerun()


# 🚦 App setup
st.set_page_config("Islamic Q&A", "🕊️")
st.title("")

st.markdown("""
<style>
html, body, .stApp {
    height: 100%;
    background-color: #000000 !important;
    background: linear-gradient(
    #000000 20%,  
    #377777 30%);


    background-attachment: fixed;
    background-size: cover;
    color: #FFFFFF;
}

/* Sidebar - solid black */
section[data-testid="stSidebar"] {
    background-color: #000000;
}
section[data-testid="stSidebar"] * {
    color: #FFFFFF !important;
}
section[data-testid="stSidebar"] input {
    background-color: rgba(255,255,255,0.1);
    color: #FFFFFF;
}

/* Markdown white text */
.stMarkdown {
    color: #FFFFFF !important;
}

/* Chat messages */
.stChatMessage {
    background-color: #000000;
    color: #FFFFFF;
    border-radius: 0.5rem;
    padding: 0.5rem;
}

/* Buttons */
.stButton > button {
    background-color: #415A77;
    color: #FFFFFF;
    border-radius: 0.5rem;
    padding: 0.5rem 1rem;
    font-weight: bold;
}
.stButton > button:hover {
    background-color: #000000;
    transform: scale(1.05);
}

/* Chat input container (bottom bar) */
section.main > div > div > div > div:nth-child(3) {
    background-color: #000000 !important;
}

/* Chat input field dark */
div[data-baseweb="input"] > div {
    background-color: #000000 !important;
    color: #000000 !important;
}
div[data-baseweb="input"] input::placeholder {
    color: rgba(255, 255, 255, 0.7) !important;
}
div[data-baseweb="input"] input {
    color: #FFFFFF !important;
}
</style>
""", unsafe_allow_html=True)




create_user_table()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None

mode = st.sidebar.radio("Choose Mode", ["Guest", "Login", "Sign Up"])

if st.session_state.authenticated:
    chat_ui()
elif mode == "Login":
    login_ui()
elif mode == "Sign Up":
    signup_ui()
else:
    chat_ui()
