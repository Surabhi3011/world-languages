# app.py
import streamlit as st
import requests
import folium
import json
from streamlit import components
from functools import lru_cache

st.set_page_config(page_title="Language Mapper", layout="wide")
st.title("Language Mapper")
st.markdown("Click a country to view official languages. Data: REST Countries • Natural Earth GeoJSON.")

# Config
GEOJSON_URL = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
REST_ALL_URL = "https://restcountries.com/v3.1/all?fields=name,cca3,languages,latlng"

# Caching network calls
@lru_cache(maxsize=1)
def fetch_geojson(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

@lru_cache(maxsize=1)
def fetch_rest_all(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

# Utility: get ISO3 candidates from GeoJSON props
def extract_iso3(props):
    if not props:
        return None
    for k in ("ISO_A3","ISO3","iso_a3","ADM0_A3","adm0_a3","CCA3","cca3","ISO_A3_EH"):
        v = props.get(k)
        if v and v != "-99":
            return v
    return None

# Prepare data
geojson = fetch_geojson(GEOJSON_URL)
rest_all = fetch_rest_all(REST_ALL_URL)

# Build mapping: cca3 -> rest entry (lowercase keys)
rest_by_cca3 = {}
rest_by_name = {}
for item in rest_all:
    cca3 = item.get("cca3")
    if cca3:
        rest_by_cca3[cca3.upper()] = item
    # store common + official names lowercase for fallback matching
    name_common = item.get("name", {}).get("common")
    if name_common:
        rest_by_name[name_common.lower()] = item

# Sidebar search
st.sidebar.header("Search")
q = st.sidebar.text_input("Country name (exact or partial)")
if st.sidebar.button("Go"):
    st.session_state._search_q = q.strip()

# Build folium map — center depends on search if found
center = [20, 0]
zoom_start = 2
search_target = None
if "_search_q" in st.session_state and st.session_state._search_q:
    qval = st.session_state._search_q.lower()
    candidate = None
    # try exact name match first in rest_by_name
    if qval in rest_by_name:
        candidate = rest_by_name[qval]
    else:
        # partial match: find first name containing q
        for name, obj in rest_by_name.items():
            if qval in name:
                candidate = obj
                break
    if candidate:
        latlng = candidate.get("latlng")
        if latlng and len(latlng) == 2:
            center = latlng
            zoom_start = 4
            search_target = candidate.get("name", {}).get("common")
    # clear search to avoid repeated runs
    st.session_state._search_q = ""

m = folium.Map(location=center, zoom_start=zoom_start, tiles="OpenStreetMap", control_scale=True)

# Add feature by feature so we can attach custom popup HTML
for feature in geojson["features"]:
    props = feature.get("properties", {}) or {}
    iso3 = extract_iso3(props)
    rest_obj = None
    if iso3:
        rest_obj = rest_by_cca3.get(str(iso3).upper())
    # fallback: match by ADMIN/NAME property
    if not rest_obj:
        geo_name = (props.get("ADMIN") or props.get("NAME") or props.get("name") or "").strip()
        if geo_name:
            rest_obj = rest_by_name.get(geo_name.lower())
            # partial fallback
            if not rest_obj:
                for nm, obj in rest_by_name.items():
                    if geo_name.lower() in nm:
                        rest_obj = obj
                        break

    # build popup content
    display_name = rest_obj.get("name", {}).get("common") if rest_obj else (props.get("ADMIN") or props.get("NAME") or props.get("name") or "Country")
    iso3_display = rest_obj.get("cca3") if rest_obj else (iso3 or "—")
    languages = []
    if rest_obj and rest_obj.get("languages"):
        languages = list(rest_obj.get("languages").values())
    official_html = ", ".join(languages) if languages else "—"
    wiki = "https://en.wikipedia.org/wiki/" + display_name.replace(" ", "_")
    popup_html = f"<div style='font-family:Arial,Helvetica,sans-serif; font-size:13px;'><b>{display_name}</b><br><b>Official:</b> {official_html}<br><b>ISO3:</b> {iso3_display}<br><a href='{wiki}' target='_blank' rel='noopener'>Wikipedia</a></div>"

    gj = folium.GeoJson(
        feature,
        style_function=lambda feat, stroke="#2b4a90", fill="#eaf2ff": {
            "color": stroke,
            "weight": 0.6,
            "fillColor": fill,
            "fillOpacity": 0.85
        }
    )
    gj.add_child(folium.Popup(popup_html, max_width=320))
    gj.add_to(m)

# Render the map HTML using folium's internal renderer and embed in Streamlit
map_html = m.get_root().render()
components.v1.html(map_html, height=720, scrolling=True)

# Optional: side info (static)
st.sidebar.markdown("---")
st.sidebar.markdown("Tip: click a country polygon on the map. Data sources: REST Countries • Natural Earth GeoJSON.")
