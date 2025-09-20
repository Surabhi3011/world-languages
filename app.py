# app.py
"""
Language Mapper - Streamlit + Folium (robust REST Countries handling)

Run:
pip install -r requirements.txt
streamlit run app.py
"""

import streamlit as st
import requests
import folium
from streamlit import components
from functools import lru_cache
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform
from pyproj import Transformer

st.set_page_config(page_title="Language Mapper", layout="wide")
st.title("Language Mapper")
st.markdown("Click a country to view official languages and metadata. Data sources: REST Countries • Natural Earth GeoJSON.")

# ----- Config -----
GEOJSON_URL = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
# initial (preferred) filtered URL; fallback will be plain /all
REST_ALL_BASE = "https://restcountries.com/v3.1/all"
REST_ALL_FIELDS = "name,cca3,languages,latlng,flags,capital,region,subregion,population,currencies,timezones"

# ----- Caching network calls -----
@lru_cache(maxsize=1)
def fetch_geojson(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_rest_all_with_fallback(base_url, fields):
    """
    Try /all?fields=... first. If it fails (HTTPError or other),
    retry /all without fields and return the full list.
    Returns list (possibly empty) and a message (None on success or info/warning).
    """
    # attempt 1: filtered
    filtered_url = f"{base_url}?fields={fields}"
    try:
        r = requests.get(filtered_url, timeout=30)
        r.raise_for_status()
        return r.json(), None
    except requests.HTTPError as e:
        # API rejected the filtered request (400/4xx/5xx). We'll retry without fields.
        msg = f"REST Countries filtered request failed ({r.status_code if 'r' in locals() else 'HTTPError'}). Retrying without fields."
        try:
            r2 = requests.get(base_url, timeout=30)
            r2.raise_for_status()
            return r2.json(), msg  # return full dataset with informational message
        except Exception as e2:
            # both attempts failed
            return [], f"Failed to fetch REST Countries data: {str(e2)}"
    except Exception as e:
        # network or other error; try unfiltered
        try:
            r2 = requests.get(base_url, timeout=30)
            r2.raise_for_status()
            return r2.json(), f"Filtered request error ({str(e)}); used unfiltered fallback."
        except Exception as e2:
            return [], f"Failed to fetch REST Countries data: {str(e2)}"

# ----- Utilities -----
def extract_iso3(props):
    if not props:
        return None
    keys = ("ISO_A3","ISO3","iso_a3","ADM0_A3","adm0_a3","CCA3","cca3","ISO_A3_EH")
    for k in keys:
        v = props.get(k)
        if v and v != "-99":
            return v
    return None

def safe_str(x):
    return str(x) if x is not None else "—"

def fmt_num(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return safe_str(n)

def bbox_to_string(bounds):
    minx, miny, maxx, maxy = bounds
    return f"SW: {round(miny,4)},{round(minx,4)} • NE: {round(maxy,4)},{round(maxx,4)}"

# ----- Prepare data -----
try:
    geojson = fetch_geojson(GEOJSON_URL)
except Exception as e:
    st.error(f"Could not load country GeoJSON: {e}")
    st.stop()

# fetch REST Countries with fallback
rest_all, rest_msg = fetch_rest_all_with_fallback(REST_ALL_BASE, REST_ALL_FIELDS)
if rest_msg:
    # show as info/warning for transparency
    st.warning(rest_msg)
if not rest_all:
    st.error("REST Countries data unavailable — app will continue but some metadata may be missing.")

# build lookup maps from whatever data we have
rest_by_cca3 = {}
rest_by_name_lower = {}
for item in rest_all:
    cca3 = item.get("cca3")
    if cca3:
        rest_by_cca3[cca3.upper()] = item
    common = item.get("name", {}).get("common")
    if common:
        rest_by_name_lower[common.lower()] = item

# default equal-area transformer
def get_transformer():
    for tgt in ("EPSG:6933", "ESRI:54009", "EPSG:3857"):
        try:
            transformer = Transformer.from_crs("EPSG:4326", tgt, always_xy=True)
            transformer.transform(0, 0)
            return transformer, tgt
        except Exception:
            continue
    return Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True), "EPSG:3857"

transformer, used_crs = get_transformer()

# ----- Build Folium map -----
center = [20, 0]
zoom_start = 2
m = folium.Map(location=center, zoom_start=zoom_start, tiles="OpenStreetMap", control_scale=True)

# Add basemap options
folium.TileLayer('CartoDB positron', name='Light').add_to(m)
folium.TileLayer('Stamen Terrain', name='Terrain').add_to(m)
folium.TileLayer('Esri.WorldImagery', name='Satellite').add_to(m)

# Feature loop (attach popups using whatever REST data we have)
for feature in geojson["features"]:
    props = feature.get("properties", {}) or {}
    iso3 = extract_iso3(props)
    rest_obj = None

    if iso3 and rest_by_cca3:
        rest_obj = rest_by_cca3.get(str(iso3).upper())

    if not rest_obj and rest_by_name_lower:
        geo_name = (props.get("ADMIN") or props.get("NAME") or props.get("name") or "").strip()
        if geo_name:
            rest_obj = rest_by_name_lower.get(geo_name.lower())
            if not rest_obj:
                for nm, obj in rest_by_name_lower.items():
                    if geo_name.lower() in nm:
                        rest_obj = obj
                        break

    display_name = rest_obj.get("name", {}).get("common") if rest_obj else (props.get("ADMIN") or props.get("NAME") or props.get("name") or "Country")
    iso3_display = rest_obj.get("cca3") if rest_obj else (iso3 or "—")
    capital = ", ".join(rest_obj.get("capital")) if rest_obj and rest_obj.get("capital") else "—"
    region = rest_obj.get("region") if rest_obj else "—"
    subregion = rest_obj.get("subregion") if rest_obj else "—"
    population = rest_obj.get("population") if rest_obj else None
    currencies = []
    if rest_obj and rest_obj.get("currencies"):
        for code, info in rest_obj["currencies"].items():
            name = info.get("name")
            currencies.append(f"{name} ({code})" if name else code)
    timezones = rest_obj.get("timezones") if rest_obj else []
    languages = []
    if rest_obj and rest_obj.get("languages"):
        languages = list(rest_obj["languages"].values())
    flag_png = None
    if rest_obj and rest_obj.get("flags"):
        flag_png = rest_obj["flags"].get("png") or rest_obj["flags"].get("svg")

    # geometry analytics
    geom = feature.get("geometry")
    area_sqkm = "—"
    centroid_lat = centroid_lon = "—"
    bbox_str = "—"
    try:
        poly = shape(geom)
        centroid = poly.centroid
        centroid_lon = round(centroid.x, 6)
        centroid_lat = round(centroid.y, 6)
        bounds = poly.bounds
        bbox_str = bbox_to_string(bounds)
        try:
            projected = shapely_transform(transformer.transform, poly)
            area_m2 = projected.area
            area_sqkm = round(area_m2 / 1e6, 2)
        except Exception:
            fallback_transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            proj2 = shapely_transform(fallback_transformer.transform, poly)
            area_m2 = proj2.area
            area_sqkm = round(area_m2 / 1e6, 2)
    except Exception:
        area_sqkm = "—"
        centroid_lat = centroid_lon = "—"
        bbox_str = "—"

    languages_html = ", ".join(languages) if languages else "—"
    currencies_html = ", ".join(currencies) if currencies else "—"
    timezones_html = ", ".join(timezones) if timezones else "—"
    population_html = fmt_num(population) if population else "—"

    popup_html = f"""
    <div style="font-family: Arial, Helvetica, sans-serif; font-size:13px; max-width:320px;">
      <div style="display:flex; gap:8px; align-items:center;">
        <div style="flex:1;">
          <b style="font-size:15px;">{display_name}</b><br/>
          <small style="color:#666">ISO3: {iso3_display}</small>
        </div>
        <div style="width:72px; text-align:right;">
          {"<img src='"+flag_png+"' width='60' style='border-radius:4px;'/>" if flag_png else ""}
        </div>
      </div>
      <hr style="margin:6px 0"/>
      <div><strong>Capital:</strong> {capital}</div>
      <div><strong>Region:</strong> {region} / {subregion}</div>
      <div><strong>Population:</strong> {population_html}</div>
      <div><strong>Currencies:</strong> {currencies_html}</div>
      <div><strong>Timezones:</strong> {timezones_html}</div>
      <div style="margin-top:6px;"><strong>Official languages:</strong> {languages_html}</div>
      <hr style="margin:6px 0"/>
      <div><strong>Area (sq.km):</strong> {safe_str(area_sqkm)}</div>
      <div><strong>Centroid (lat,lon):</strong> {centroid_lat}, {centroid_lon}</div>
      <div><strong>Bounding box:</strong> {bbox_str}</div>
      <div style="margin-top:6px;"><a href="https://en.wikipedia.org/wiki/{display_name.replace(' ','_')}" target="_blank">Wikipedia</a></div>
    </div>
    """

    gj = folium.GeoJson(
        feature,
        style_function=lambda feat, stroke="#2b4a90", fill="#eaf2ff": {
            "color": stroke,
            "weight": 0.6,
            "fillColor": fill,
            "fillOpacity": 0.85,
        },
        highlight_function=lambda feat: {"weight": 1.8, "color": "#0b3d91", "fillOpacity": 0.95}
    )
    gj.add_child(folium.Popup(popup_html, max_width=360))
    gj.add_to(m)

folium.LayerControl(position='topright').add_to(m)

map_html = m.get_root().render()
components.v1.html(map_html, height=760, scrolling=True)

st.markdown("---")
st.markdown(f"Note: area computed by projecting to {used_crs} (equal-area preference). Values are approximate.")
