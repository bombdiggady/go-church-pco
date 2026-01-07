import streamlit as st
import requests
import google.generativeai as genai
import os
import json
from datetime import datetime

# --- CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="GO Church PCO Helpdesk",
    page_icon="⛪",
    layout="wide"
)

# Load secrets from Streamlit's secret management
try:
    PCO_APP_ID = st.secrets["PCO_APPLICATION_ID"]
    PCO_SECRET = st.secrets["PCO_SECRET"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    st.error("❌ Missing API Keys. Please configure your secrets in Streamlit.")
    st.stop()

# Configure Gemini
genai.configure(api_key=GOOGLE_API_KEY)
BASE_URL = "https://api.planningcenteronline.com"

# --- HELPER FUNCTIONS ---

def pco_api_call(endpoint, params=None):
    """Generic function to call PCO API securely."""
    auth = (PCO_APP_ID, PCO_SECRET)
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", auth=auth, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 403:
            return {"error": "Access Denied (Check Permissions)"}
        else:
            return {"error": f"Status {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

def search_context(query):
    """
    Performs a 'federated search' across allowed PCO modules.
    Strictly ignores Giving.
    """
    context_data = []

    # 1. Search PEOPLE
    # We search for the name provided in the query
    people_data = pco_api_call("/people/v2/people", params={"where[search_name_or_email]": query, "per_page": 3})
    if "data" in people_data and people_data["data"]:
        names = [f"{p['attributes']['name']} ({p['attributes']['status']})" for p in people_data['data']]
        context_data.append(f"Found in People Database: {', '.join(names)}")

    # 2. Search SERVICES (Plans)
    # Get the most recent/upcoming plans
    services_data = pco_api_call("/services/v2/service_types")
    if "data" in services_data and services_data["data"]:
        service_names = [s['attributes']['name'] for s in services_data['data'][:5]]
        context_data.append(f"Available Service Types: {', '.join(service_names)}")
    
    # 3. Search CALENDAR
    # Look for events matching the query
    calendar_data = pco_api_call("/calendar/v2/events", params={"where[title]": query, "per_page": 3})
    if "data" in calendar_data and calendar_data["data"]:
        events = [f"{e['attributes']['title']} (Visible in Kiosks: {e['attributes']['visible_in_kiosks']})" for e in calendar_data['data']]
        context_data.append(f"Found in Calendar: {', '.join(events)}")

    # 4. Search GROUPS
    groups_data = pco_api_call("/groups/v2/groups", params={"where[name]": query, "per_page": 3})
    if "data" in groups_data and groups_data["data"]:
        groups = [g['attributes']['name'] for g in groups_data['data']]
        context_data.append(f"Found in Groups: {', '.join(groups)}")

    if not context_data:
        return "No specific data found in People, Services, Calendar, or Groups for this query."
    
    return "\n".join(context_data)

# --- USER INTERFACE ---

st.title("⛪ GO Church PCO Helpdesk")
st.markdown("""
This tool uses AI to answer questions about our church database. 
**Note:** Financial/Giving data is strictly private and not accessible here.
""")

# Sidebar for tips
with st.sidebar:
    st.header("How to use")
    st.info("Ask specifically, e.g., 'Is John Doe in our database?' or 'What events are on the calendar?'")
    st.warning("Data is Read-Only. You cannot change PCO data here.")

# Chat Logic
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask a question about GO Church PCO..."):
    # 1. User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Assistant Processing
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("🔍 *Searching PCO Database...*")
        
        # A. Fetch Real Data
        retrieved_info = search_context(prompt)
        
        # B. AI Synthesis
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        system_prompt = f"""
        You are a helpful PCO administrator for GO Church.
        User Query: {prompt}
        
        Here is the REAL data found in the PCO account matching their query:
        ---
        {retrieved_info}
        ---
        
        INSTRUCTIONS:
        1. Answer the user's question using the retrieved data.
        2. If the retrieved data is empty, give general advice on where to look in PCO.
        3. Tone: Friendly, church-staff professional.
        4. ABSOLUTE RULE: Never mention Giving, Donations, or Tithes details. If asked, say you don't have access.
        """
        
        try:
            response = model.generate_content(system_prompt)
            full_response = response.text
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e:
            message_placeholder.error("An error occurred connecting to AI.")