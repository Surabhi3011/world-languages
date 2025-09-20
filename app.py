# app.py
import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from functools import lru_cache

# -------------------------
# Config / layout
# -------------------------
st.set_page_config(page_title="Language Mapper", layout="wide")
st.markdown("<h1 style='margin:0 0 6px'>Language Mapper</h1>", unsafe_allow_html=True)
st.markdown("Click a country on the map to view its official and top spoken languages. Data: REST Countries • Natural Earth GeoJSON.")

COLORS = {
    "fill": "#eaf2ff",
    "stroke": "#2b4a90",
}

GEOJSON_URL = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"

# -------------------------
# Caching data fetches
# -------------------------
@lru_cache(maxsize=2)
def fetch_geojson(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

@lru_cache(maxsize=512)
def restcountries_by_alpha(alpha3):
    url = f"https://restcountries.com/v3.1/alpha/{alpha3}?fields=name,languages,cca3,latlng"
    r = requests.get(url, timeout=15)
    if r.ok:
        data = r.json()
        return data[0] if isinstance(data, list) else data
    return None

@lru_cache(maxsize=512)
def restcountries_by_name(name):
    # try fullText first, then fallback
    for q in [f"https://restcountries.com/v3.1/name/{name}?fullText=true&fields=name,languages,cca3,latlng",
              f"https://restcountries.com/v3.1/name/{name}?fields=name,languages,cca3,latlng"]:
        r = requests.get(q, timeout=15)
        if r.ok:
            data = r.json()
            return data[0] if isinstance(data, list) else data
    return None

# -------------------------
# Sidebar controls & info
# -------------------------
st.sidebar.title("Controls")
search_query = st.sidebar.text_input("Search country (name)", "")
if st.sidebar.button("Find"):
    st.session_state.get_country = search_query.strip()

st.sidebar.markdown("---")
st.sidebar.markdown("**Selected country info**")
selected_info = st.sidebar.empty()
st.sidebar.markdown("---")
st.sidebar.markdown("Data sources: REST Countries • Natural Earth • App by you")

# -------------------------
# Build folium map
# -------------------------
geojson = fetch_geojson(GEOJSON_URL)

m = folium.Map(location=[20, 0], zoom_start=2, tiles="OpenStreetMap", control_scale=True)

def style_function(feature):
    return {
        "fillColor": COLORS["fill"],
        "color": COLORS["stroke"],
        "weight": 0.6,
        "fillOpacity": 0.85,
    }

def highlight_function(feature):
    return {"weight": 1.8, "color": "#0b3d91", "fillOpacity": 0.95}

# add GeoJSON layer
gj = folium.GeoJson(
    geojson,
    style_function=style_function,
    highlight_function=highlight_function,
    tooltip=folium.GeoJsonTooltip(fields=["ADMIN"], aliases=["Country"], localize=True),
    name="countries",
).add_to(m)

# Important: st_folium will return "last_object_clicked" when a GeoJson feature is clicked.
map_data = st_folium(m, width=1100, height=700, returned_objects=["last_object_clicked"])

# -------------------------
# Handle clicks & search
# -------------------------
def show_country_info_from_feature(feature):
    props = feature.get("properties", {}) if feature else {}
    name_candidates = [props.get("ADMIN"), props.get("NAME"), props.get("name"), props.get("SOVEREIGNT")]
    country_name = next((n for n in name_candidates if n), "Unknown")
    # ISO3 extraction from common properties
    iso3 = None
    for k in ("ISO_A3","ISO3","iso_a3","ADM0_A3","adm0_a3","CCA3","cca3","FORMAL_EN"):
        v = props.get(k)
        if v and v != "-99":
            iso3 = v
            break

    # Use REST Countries (alpha3 preferred; fallback to name)
    data = None
    if iso3:
        try:
            data = restcountries_by_alpha(iso3)
        except Exception:
            data = None
    if not data:
        try:
            data = restcountries_by_name(country_name)
        except Exception:
            data = None

    # Build display
    display = {}
    display["display_name"] = data.get("name", {}).get("common") if data else country_name
    display["iso3"] = data.get("cca3") if data else (iso3 or "—")
    display["latlng"] = data.get("latlng") if data else None
    languages = data.get("languages") if data else None
    display["official_languages"] = list(languages.values()) if languages else []
    return display

clicked = map_data.get("last_object_clicked")
info = None
if clicked:
    info = show_country_info_from_feature(clicked)
elif "get_country" in st.session_state and st.session_state.get_country:
    # user used search box; try resolving to country info (and recenter map)
    name = st.session_state.get_country
    info = restcountries_by_name(name)
    if info:
        info = {
            "display_name": info.get("name", {}).get("common", name),
            "iso3": info.get("cca3"),
            "latlng": info.get("latlng"),
            "official_languages": list(info.get("languages", {}).values()) if info.get("languages") else []
        }
        # center the map to the country's latlng by re-rendering map with new center
        if info.get("latlng"):
            # note: st.experimental_rerun could be used but simpler to show instruction to user to click map center
            st.success(f"Found {info['display_name']}. Click on the map feature to view full info and zoom.")
    else:
        st.warning("Country not found via REST Countries. Try different name.")
    # clear session state to prevent repeated searches
    st.session_state.get_country = ""

# Display info in sidebar
if info:
    display_name = info.get("display_name", "Unknown")
    st.sidebar.markdown(f"### {display_name}")
    st.sidebar.write(f"**ISO3:** {info.get('iso3','—')}")
    langs = info.get("official_languages", [])
    if langs:
        st.sidebar.write("**Official languages:**")
        for l in langs:
            st.sidebar.write(f"- {l}")
    else:
        st.sidebar.write("**Official languages:** —")

    # Top spoken: Best-effort, use official list as fallback
    top_spoken = langs[:3] if langs else []
    st.sidebar.write("**Top spoken (best-effort):**")
    if top_spoken:
        st.sidebar.write(", ".join(top_spoken))
    else:
        st.sidebar.write("—")

    # Wikipedia link
    wiki_name = display_name.replace(" ", "_")
    st.sidebar.markdown(f"[Open Wikipedia page](https://en.wikipedia.org/wiki/{wiki_name})")

    # Copy area for easy copy/paste
    st.sidebar.text_area("Copy languages (select & copy):", value=", ".join(langs) if langs else display_name, height=80)
else:
    st.sidebar.markdown("Click a country on the map to show its languages here.")

# Small footer in the main body
st.markdown("---")
st.markdown("Tip: Use the search box in the sidebar to pre-find a country. Click the country polygon on the map for full info. Data: REST Countries • Natural Earth.")
