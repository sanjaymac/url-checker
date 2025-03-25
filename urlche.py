import streamlit as st
import requests
import time
import re
import pandas as pd

API_BASE = "https://check-host.net"

def get_csrf_token(html):
    token_match = re.search(r'name="csrf_token" value="(.+?)"', html)
    return token_match.group(1) if token_match else None

def check_url(url):
    """Trigger a bulk HTTP check via the API."""
    try:
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/html;q=0.9"}
        params = {"host": url}
        response = session.get(f"{API_BASE}/check-http", params=params, headers=headers, timeout=10)
        # If response is HTML, try to extract the CSRF token and re-submit.
        if not response.text.lstrip().startswith("{"):
            token = get_csrf_token(response.text)
            if not token:
                st.error(f"Unable to extract CSRF token for {url}")
                return None
            params["csrf_token"] = token
            response = session.get(f"{API_BASE}/check-http", params=params, headers=headers, timeout=10)
            if not response.text.lstrip().startswith("{"):
                st.error(f"Expected JSON but received HTML even after CSRF token submission for {url}")
                return None
        data = response.json()
        request_id = data.get("request_id")
        if not request_id:
            st.error("No request_id received for " + url)
            return None

        # Poll for results (up to 10 times with a 2-second delay)
        for _ in range(10):
            time.sleep(2)
            result_response = session.get(f"{API_BASE}/check-result/{request_id}", headers=headers, timeout=10)
            if not result_response.text.strip():
                continue
            try:
                result_data = result_response.json()
            except ValueError:
                st.error(f"Invalid JSON in results for {url}: {result_response.text}")
                return None
            if result_data:
                return result_data
        st.error(f"Timeout: Failed to retrieve results for {url}.")
        return None
    except Exception as e:
        st.error(f"Error checking {url}: {e}")
        return None

def analyze_result(result):
    """
    Analyze the API result.
    The result is a dict where each key is a node identifier and its value is a list of lists:
       [ [ success_flag, time, message, http_status, ip ] ]
    Returns a list of active node IDs.
    """
    active_nodes = []
    for node, res in result.items():
        if not res or not isinstance(res, list) or not res[0]:
            continue
        check = res[0]
        try:
            success_flag = int(check[0])
            status_code = int(check[3]) if check[3] is not None else None
        except Exception:
            continue
        if success_flag == 1 and status_code and 200 <= status_code < 400:
            active_nodes.append(node)
    return active_nodes

def map_node_to_country(node_id):
    """
    Map a node id to a country name using its two-letter prefix.
    Extend this mapping as needed.
    """
    mapping = {
        "us": "USA",
        "ch": "Switzerland",
        "pt": "Portugal",
        "ru": "Russia",
        "de": "Germany",
        "in": "India",
        "uk": "United Kingdom",
        "fr": "France",
        "jp": "Japan",
        # add other mappings as needed
    }
    prefix = node_id[:2].lower()
    return mapping.get(prefix, node_id)

def check_with_scraping(url):
    """
    Attempt to access the URL directly.
    Returns a tuple (active_flag, message) where active_flag is True if the HTTP response is in the 200-399 range.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        if 200 <= response.status_code < 400:
            return True, f"HTTP {response.status_code}"
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)

def main():
    st.title("URL status Checker")
    st.write(
        "Enter one or more URLs (one per line). The app first attempts a direct (scraping) check. "
        "If that check succeeds, the URL is marked as active (direct) and no further check is done. "
        "If the direct check fails, the app falls back to an API check. "
        "For the API check, any active node mapping to India is ignored; only other active nodes are considered."
    )
    
    urls_text = st.text_area("Enter URLs:", height=200)
    results = []
    
    if st.button("Check URLs"):
        urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
        if not urls:
            st.warning("Please enter at least one URL.")
            return
        
        for url in urls:
            st.write(f"### Checking: {url}")
            row = {"URL": url, "Status": "", "Other Active Countries": ""}
            
            # First, try the direct scraping check.
            scraping_active, scraping_result = check_with_scraping(url)
            if scraping_active:
                row["Status"] = "Active (Direct)"
                st.success(f"Direct check succeeded: {scraping_result}")
            else:
                st.error(f"Direct check failed: {scraping_result}")
                st.info("Falling back to API check...")
                bulk_result = check_url(url)
                if bulk_result:
                    active_nodes = analyze_result(bulk_result)
                    if active_nodes:
                        # Map nodes to country names.
                        active_countries = [map_node_to_country(n) for n in active_nodes]
                        # Filter out any nodes that map to India.
                        filtered_countries = [c for c in active_countries if c != "India"]
                        if filtered_countries:
                            row["Status"] = "Active (Other Countries)"
                            row["Other Active Countries"] = ", ".join(filtered_countries)
                            st.info(f"API check: Active nodes (excluding India): {row['Other Active Countries']}")
                        else:
                            row["Status"] = "Inactive (No non-India nodes)"
                            st.error("API check found only nodes from India, which are being ignored.")
                    else:
                        row["Status"] = "Inactive"
                        st.error("No active nodes found via API.")
                else:
                    row["Status"] = "Error retrieving API data"
                    st.error("Failed to retrieve API check results.")
            
            results.append(row)
        
        # Display and allow download of the results.
        df = pd.DataFrame(results)
        st.subheader("Results")
        st.dataframe(df)
        csv = df.to_csv(index=False)
        st.download_button("Download CSV", csv, "url_check_results.csv", "text/csv")

if __name__ == '__main__':
    main()
