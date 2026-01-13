def search_context(query):
    """
    Performs a search with Deep Diagnostics to catch 'Empty Room' errors.
    """
    context_data = []
    debug_log = []
    
    # Clean the query (remove accidental spaces)
    clean_query = query.strip()

    # 0. DIAGNOSTIC: Check which Organization we are connected to
    # This ensures we aren't searching a test account by mistake.
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
            names = [f"{p['attributes'].get('name')} ({p['attributes'].get('status')})" for p in people]
            context_data.append(f"Found in People Directory: {', '.join(names)}")
        else:
            debug_log.append(f"⚠️ People API: 0 results for '{clean_query}'. Trying partial search...")
            
            # RETRY: Try searching just the first word (e.g., "Alex" instead of "Alex Miller")
            first_word = clean_query.split(' ')[0]
            if len(first_word) > 2 and first_word != clean_query:
                retry_res = pco_api_call("/people/v2/people", params={"where[search_name_or_email]": first_word, "per_page": 3})
                if retry_res and retry_res.status_code == 200:
                    retry_data = retry_res.json().get("data", [])
                    if retry_data:
                        found_people = True
                        debug_log.append(f"✅ People API: Retry found {len(retry_data)} matches for '{first_word}'")
                        names = [f"{p['attributes'].get('name')} ({p['attributes'].get('status')})" for p in retry_data]
                        context_data.append(f"No exact match, but found similar names: {', '.join(names)}")
                    else:
                        debug_log.append(f"❌ People API: Retry also found 0 records for '{first_word}'.")

    elif res and res.status_code == 403:
        context_data.append("ERROR: Permission Denied to People Database.")
        debug_log.append("❌ People API: 403 Forbidden (Check API Key Scopes)")

    # 2. Search SERVICES (Gatherings)
    res = pco_api_call("/services/v2/service_types")
    if res and res.status_code == 200:
        data = res.json().get("data", [])
        debug_log.append(f"✅ Services API: Success. Found {len(data)} Gathering Types.")
        # Only list names if we haven't found a person yet, to save token space
        if not found_people:
             types = [s['attributes'].get('name') for s in data[:5]]
             context_data.append(f"Gathering Types: {', '.join(types)}")

    # 3. Search CALENDAR
    # Calendar searches for EVENTS, not People.
    res = pco_api_call("/calendar/v2/events", params={"where[name]": clean_query, "per_page": 3})
    if res and res.status_code == 200:
        events = res.json().get("data", [])
        if events:
            debug_log.append(f"✅ Calendar API: Found {len(events)} events.")
            event_names = [e['attributes'].get('name') for e in events]
            context_data.append(f"Calendar Events: {', '.join(event_names)}")
        else:
            debug_log.append("✅ Calendar API: 0 events found.")

    return "\n".join(context_data), "\n".join(debug_log)
