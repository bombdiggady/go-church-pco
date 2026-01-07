import streamlit as st
import requests
import google.generativeai as genai
import os

# --- CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="GO Church PCO Helpdesk",
    page_icon="⛪",
    layout="wide"
)

# Load secrets
try:
    PCO_APP_ID = st.secrets["PCO_APPLICATION_ID"]
    PCO_SECRET = st.secrets["PCO_SECRET"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    st.error("❌ Missing API Keys. Please configure your secrets in Streamlit.")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
BASE_URL = "https://api.planningcenteronline.com"

# --- HELPER FUNCTIONS ---

def pco_api_call(endpoint, params=None):
    """Generic function to call PCO API securely."""
    auth = (PCO_APP_ID, PCO_SECRET)
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", auth=auth, params=params, timeout=10)
        # return the full object so we can debug status codes
        return response
    except Exception as e:
        return None

def search_context(query):
    """
    Performs a search across modules and returns a tuple: (Readable Text, Debug Log)
    """
    context_data = []
    debug_log = [] # Log everything for the 'Debug Mode'

    # 1. Search PEOPLE
    # We search specifically by name
    res = pco_api_call("/people/v2/people", params={"where[search_name_or_email]": query, "per_page": 3})
    
    if res is None:
        debug_log.append("❌ People API: Connection Failed")
    elif res.status_code == 403:
        debug_log.append("❌ People API: 403 Forbidden (Check API Key 'People' Scope)")
        context_data.append("ERROR: The API Key does not have permission to view People.")
    elif res.status_code == 200:
        data = res.json().get("data", [])
        debug_log.append(f"✅ People API: Success. Found {len(data)} records.")
        if data:
            names = [f"{p['attributes'].get('name', 'Unknown')} ({p['attributes'].get('status', 'Unknown')})" for p in data]
            context_data.append(f"Found in People Database: {', '.join(names)}")
    else:
        debug_log.append(f"⚠️ People API: Unexpected Status {res.status_code}")

    # 2. Search CALENDAR
    # Calendar uses 'where[name]' as a fuzzy search
    res = pco_api_call("/calendar/v2/events", params={"where[name]": query, "per_page": 5, "order": "starts_at"})
    
    if res and res.status_code == 200:
        data = res.json().get("data", [])
        debug_log.append(f"✅ Calendar API: Success. Found {len(data)} events.")
        if data:
            events = []
            for e in data:
                # Try to get the next date if available
                name = e['attributes'].get('name', 'Unnamed')
                events.append(f"Event: {name}")
            context_data.append(f"Found in Calendar: {', '.join(events)}")
    elif res and res.status_code == 403:
         debug_log.append("❌ Calendar API: 403 Forbidden")

    # 3. Search SERVICES (Gatherings)
    # Note: We are only listing Types, not Plans (Dates), which is why it can't find specific dates yet.
    res = pco_api_call("/services/v2/service_types")
    if res and res.status_code == 200:
        data = res.json().get("data", [])
        debug_log.append(f"✅ Services API: Success. Found {len(data)} types.")
        service_names = [s['attributes'].get('name', 'Unnamed') for s in data[:10]]
        context_data.append(f"Available Gathering Types: {', '.join(service_names)}")

    return "\n".join(context_data), "\n".join(debug_log)

# --- USER INTERFACE ---

st.title("⛪ GO Church PCO Helpdesk")

# Sidebar
with st.sidebar:
    st.header("Settings")
    # THE NEW DEBUG TOGGLE
    show_debug = st.checkbox("Show Debug Logs", value=False)
    st.markdown("---")
    st.info("Ask specifically, e.g., 'Is John Doe in our database?'")

# Chat Logic
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask a question about GO Church PCO..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("🔍 *Searching PCO Database...*")
        
        # Get data AND debug logs
        retrieved_info, debug_info = search_context(prompt)
        
        # Show debug info if checked
        if show_debug:
            st.warning(f"**DEBUG LOG:**\n\n{debug_info}")
            st.text(f"Raw Data Passed to AI:\n{retrieved_info}")

        # PCO Knowledge Base
        pco_knowledge_base = """
        PCO STRUCTURE & CONTEXT:
        - **People:** The master database. "Status" = Member, Regular Attender, Visitor.
        - **Gatherings (PCO "Services"):** GO Church calls these "Gatherings".
        - **Calendar:** Room bookings and public events.
        """

        system_prompt = f"""
        You are the "GO Church PCO Specialist".
        
        TERMINOLOGY:
        - Use "Gatherings" instead of "Services".

        REAL-TIME DATA FOUND:
        ---
        {retrieved_info}
        ---
        
        INSTRUCTIONS:
        1. If you see "ERROR" or "Permission denied" in the data, tell the user their API Key needs fixing.
        2. If the data is empty, suggest where they can look in PCO manually.
        3. Never discuss Giving/Donations.

        User Question: {prompt}
        """
        
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(system_prompt)
            full_response = response.text
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e:
            message_placeholder.error(f"AI Error: {e}")
