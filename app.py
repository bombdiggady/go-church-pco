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
        # return the full object so we can debug status codes
        return response
    except Exception as e:
        return None

def search_context(query):
    """
    Performs a 'federated search' across allowed PCO modules with Deep Diagnostics.
    Strictly ignores Giving.
    """
    context_data = []
    debug_log = []
    
    # Clean the query (remove accidental spaces)
    clean_query = query.strip()

    # 0. DIAGNOSTIC: Check which Organization we are connected to
    org_res = pco_api_call("/")
    if org_res and org_res.status_code == 200:
        org_name = org_res.json().get("data", {}).get("attributes", {}).get("name", "Unknown Org")
        debug_log.append(f"🏢 Connected to Organization: **{org_name}**")
    else:
        debug_log.append("❌ Org Check: Failed to connect to PCO Root.")

    # 1. Search PEOPLE (With Retry Logic)
    # First attempt: Search full query
    res = pco_api_call("/people/v2/people", params={"where[search_name_or_email]": clean_query, "per_page": 5})
    
    found_people = False
    if res and res.status_code == 200:
        people = res.json().get("data", [])
        if people:
            found_people = True
            debug_log.append(f"✅ People API: Found {len(people)} matches for '{clean_query}'")
            names = [f"{p['attributes'].get('name', 'Unknown')} ({p['attributes'].get('status', 'Unknown')})" for p in people]
            context_data.append(f"Found in People Directory: {', '.join(names)}")
        else:
            debug_log.append(f"⚠️ People API: 0 results for '{clean_query}'. Trying partial search...")
            
            # RETRY: Try searching just the first word (e.g., "Alex" instead of "Alex Miller")
            first_word = clean_query.split(' ')[0]
            # Only retry if the first word is distinct from the full query
            if len(first_word) > 2 and first_word != clean_query:
                retry_res = pco_api_call("/people/v2/people", params={"where[search_name_or_email]": first_word, "per_page": 3})
                if retry_res and retry_res.status_code == 200:
                    retry_data = retry_res.json().get("data", [])
                    if retry_data:
                        found_people = True
                        debug_log.append(f"✅ People API: Retry found {len(retry_data)} matches for '{first_word}'")
                        names = [f"{p['attributes'].get('name', 'Unknown')} ({p['attributes'].get('status', 'Unknown')})" for p in retry_data]
                        context_data.append(f"No exact match, but found similar names: {', '.join(names)}")
                    else:
                        debug_log.append(f"❌ People API: Retry also found 0 records for '{first_word}'.")
            else:
                 debug_log.append("❌ People API: Partial search skipped (query too short).")

    elif res and res.status_code == 403:
        context_data.append("ERROR: Permission Denied to People Database.")
        debug_log.append("❌ People API: 403 Forbidden (Check API Key 'People' Scope)")

    # 2. Search SERVICES (Gatherings)
    # We always fetch this to give context about upcoming events
    res = pco_api_call("/services/v2/service_types")
    if res and res.status_code == 200:
        data = res.json().get("data", [])
        debug_log.append(f"✅ Services API: Success. Found {len(data)} Gathering Types.")
        # Only list specific names if the user didn't find a person (to save reading time)
        types = [s['attributes'].get('name', 'Unnamed') for s in data[:8]]
        context_data.append(f"Available Gathering Types: {', '.join(types)}")
    elif res and res.status_code == 403:
        debug_log.append("❌ Services API: 403 Forbidden")

    # 3. Search CALENDAR
    res = pco_api_call("/calendar/v2/events", params={"where[name]": clean_query, "per_page": 3})
    if res and res.status_code == 200:
        events = res.json().get("data", [])
        if events:
            debug_log.append(f"✅ Calendar API: Found {len(events)} events.")
            event_names = [e['attributes'].get('name', 'Unnamed') for e in events]
            context_data.append(f"Found in Calendar: {', '.join(event_names)}")
        else:
            debug_log.append("✅ Calendar API: 0 events found.")

    # 4. Search GROUPS
    res = pco_api_call("/groups/v2/groups", params={"where[name]": clean_query, "per_page": 3})
    if res and res.status_code == 200:
        groups = res.json().get("data", [])
        if groups:
            debug_log.append(f"✅ Groups API: Found {len(groups)} groups.")
            group_names = [g['attributes'].get('name', 'Unnamed') for g in groups]
            context_data.append(f"Found in Groups: {', '.join(group_names)}")
    
    # Final Output Construction
    final_output = "\n".join(context_data)
    
    if not final_output:
        final_output = "No specific data found in People, Services, Calendar, or Groups for this query."
    
    return final_output, "\n".join(debug_log)

# --- USER INTERFACE ---

st.title("⛪ GO Church PCO Helpdesk")
st.markdown("""
This tool uses AI to answer questions about the **GO Church** database. 
**Note:** Financial/Giving data is strictly private and not accessible here.
""")

# Sidebar
with st.sidebar:
    st.header("Settings")
    show_debug = st.checkbox("Show Debug Logs", value=False)
    
    st.markdown("---")
    st.header("How to use")
    st.info("Ask specifically, e.g., 'Is Alex Miller in our database?' or 'When is the next Gathering?'")
    st.warning("Data is Read-Only.")
    st.markdown("---")
    st.markdown("[📚 Official PCO Support](https://support.planningcenteronline.com/hc/en-us)")

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
        
        # A. Fetch Real Data with Diagnostics
        retrieved_info, debug_info = search_context(prompt)
        
        # Show debug if requested
        if show_debug:
            st.warning(f"**DEBUG LOG:**\n\n{debug_info}")
            st.text(f"Raw Context Sent to AI:\n{retrieved_info}")
        
        # B. AI Synthesis
        # Updated Model to 2.5 Flash
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Knowledge Base Injection
        pco_knowledge_base = """
        PCO STRUCTURE & CONTEXT:
        - **People:** The master database of members. "Status" usually refers to Member, Regular Attender, or Visitor.
        - **Gatherings (PCO "Services"):** GO Church calls liturgical services "Gatherings". In the API, this is the "Services" module.
        - **Calendar:** The master church calendar for room booking and public events.
        - **Check-ins:** Used primarily for Kids Ministry and attendance tracking.
        - **Groups:** Small groups, Bible studies, and home groups.
        
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
        3. **Contextualize:** If looking for "John," understand that if he is in "Gatherings," he is likely scheduled to serve; if in "People," it's his profile.
        4. **Giving Firewall:** NEVER discuss giving, donations, or financial stats. If asked, state: "I do not have access to financial data."
        5. **Support Link:** If you cannot answer, suggest they search the official PCO support site.

        User Question: {prompt}
        """
        
        try:
            response = model.generate_content(system_prompt)
            full_response = response.text
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e:
            message_placeholder.error(f"AI Error: {e}")
