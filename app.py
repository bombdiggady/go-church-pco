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
    people_data = pco_api_call("/people/v2/people", params={"where[search_name_or_email]": query, "per_page": 3})
    if "data" in people_data and people_data["data"]:
        # Safely get name, default to "Unknown" if missing
        names = [f"{p['attributes'].get('name', 'Unknown')} ({p['attributes'].get('status', 'Unknown')})" for p in people_data['data']]
        context_data.append(f"Found in People Database: {', '.join(names)}")

    # 2. Search SERVICES (Plans)
    services_data = pco_api_call("/services/v2/service_types")
    if "data" in services_data and services_data["data"]:
        service_names = [s['attributes'].get('name', 'Unnamed Service') for s in services_data['data'][:5]]
        context_data.append(f"Available Service Types: {', '.join(service_names)}")
    
    # 3. Search CALENDAR (FIXED)
    # Changed 'title' to 'name' to match PCO API standards
    calendar_data = pco_api_call("/calendar/v2/events", params={"where[name]": query, "per_page": 3})
    if "data" in calendar_data and calendar_data["data"]:
        events = []
        for e in calendar_data['data']:
            attrs = e.get('attributes', {})
            # Use .get() to prevent crashes if a field is missing
            name = attrs.get('name', 'Unnamed Event')
            events.append(name)
        context_data.append(f"Found in Calendar: {', '.join(events)}")

    # 4. Search GROUPS
    groups_data = pco_api_call("/groups/v2/groups", params={"where[name]": query, "per_page": 3})
    if "data" in groups_data and groups_data["data"]:
        groups = [g['attributes'].get('name', 'Unnamed Group') for g in groups_data['data']]
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
    st.info("Ask specifically, e.g., 'Is John Doe in our database?'")
    st.warning("Data is Read-Only.")
    st.markdown("---") 
    st.markdown("[📚 Official PCO Support](https://support.planningcenteronline.com/hc/en-us)") # <--- ADD THIS

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
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # DYNAMIC KNOWLEDGE BASE
        # We inject this text so the AI understands PCO terminology & GO Church lingo
        pco_knowledge_base = """
        PCO STRUCTURE & CONTEXT:
        - **People:** The master database of members. "Status" usually refers to Member, Regular Attender, or Visitor.
        - **Gatherings (PCO "Services"):** GO Church calls liturgical services "Gatherings". In the API, this is the "Services" module.
        - **Calendar:** The master church calendar for room booking and public events.
        - **Check-ins:** Used primarily for Kids Ministry and attendance tracking.
        - **Groups:** Small groups, Bible studies, and home groups.
        - **Registrations:** Sign-ups for events (camps, retreats).
        
        OFFICIAL SUPPORT RESOURCE:
        If the API data is insufficient, refer the user to: https://support.planningcenteronline.com/hc/en-us
        """

        system_prompt = f"""
        You are the "GO Church PCO Specialist"—a helpful, friendly AI assistant for church staff.
        
        YOUR GOAL:
        Help staff find information in the GO Church PCO account and understand how to use PCO better.

        TERMINOLOGY RULE:
        - **"Gatherings" vs "Services":** The PCO database calls them "Services", but GO Church calls them "Gatherings". 
        - If the user asks about "Services", understand they mean Gatherings.
        - In your output, ALWAYS refer to them as "Gatherings" (e.g., "I found 3 upcoming Gatherings...").

        CONTEXT:
        {pco_knowledge_base}
        
        REAL-TIME DATA FROM GO CHURCH ACCOUNT:
        ---
        {retrieved_info}
        ---
        
        INSTRUCTIONS:
        1. **Prioritize Real Data:** If the answer is in the "REAL-TIME DATA" section above, quote it explicitly.
        2. **Fill the Gaps:** If the user asks a "How-to" question (e.g., "How do I add a song?"), rely on your general knowledge of Planning Center Online to explain the steps.
        3. **Giving Firewall:** NEVER discuss giving, donations, or financial stats. If asked, state: "I do not have access to financial data."
        4. **Support Link:** If you cannot answer, suggest they search the official PCO support site.

        User Question: {prompt}
        """
        
        try:
            response = model.generate_content(system_prompt)
            full_response = response.text
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e:

            message_placeholder.error(f"An error occurred connecting to AI: {e}")






