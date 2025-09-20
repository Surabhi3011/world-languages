# app.py
"""
Language Mapper - Streamlit + Folium

Features:
- Click any country polygon to open a popup with:
  flag, capital, region, population, currencies, timezones, centroid coords,
  area (sq.km), bounding box.
- Server-side prefetch of REST Countries (single /all request).
- Uses Shapely + PyProj for area and centroid calculations.
- Embeds Folium HTML using st.components.v1.html to avoid st_folium render issues.

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

# ----- Config -----
st.set_page_config(page_title="Language Mapper", layout="wide")
st.title("Language Mapper")
st.markdown("Click a country to view official languages and metadata. Data sources: REST Countries • Natural Earth GeoJSON.")

# URLs
GEOJSON_URL = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
REST_ALL_URL = (
    "https://restcountries.com/v3.1/all?fields=name,cca3,languages,latlng,flags,capital,region,subregion,population,currencies,timezones"
)

# ----- Caching network calls -----
@lru_cache(maxsize=1)
def fetch_geojson(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

@lru_cache(maxsize=1)
def fetch_rest_all(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

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
    # bounds is (minx, miny, maxx, maxy) -> lon/lat
    minx, miny, maxx, maxy = bounds
    return f"SW: {round(miny,4)},{round(minx,4)} • NE: {round(maxy,4)},{round(maxx,4)}"

# ----- Prepare data -----
geojson = fetch_geojson(GEOJSON_URL)
rest_all = fetch_rest_all(REST_ALL_URL)

# build lookup maps
rest_by_cca3 = {}
rest_by_name_lower = {}
for item in rest_all:
    cca3 = item.get("cca3")
    if cca3:
        rest_by_cca3[cca3.upper()] = item
    common = item.get("name", {}).get("common")
    if common:
        rest_by_name_lower[common.lower()] = item

# Default equal-area transformer pref (try EPSG:6933, fallback to Mollweide ESRI:54009, then EPSG:3857)
def get_transformer():
    for tgt in ("EPSG:6933", "ESRI:54009", "EPSG:3857"):
        try:
            transformer = Transformer.from_crs("EPSG:4326", tgt, always_xy=True)
            # quick test transform
            transformer.transform(0, 0)
            return transformer, tgt
        except Exception:
            continue
    # last resort
    return Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True), "EPSG:3857"

transformer, used_crs = get_transformer()

# ----- Build Folium map -----
center = [20, 0]
zoom_start = 2
m = folium.Map(location=center, zoom_start=zoom_start, tiles="OpenStreetMap", control_scale=True)

# Add a few basemap options
folium.TileLayer('CartoDB positron', name='Light').add_to(m)
folium.TileLayer('Stamen Terrain', name='Terrain').add_to(m)
folium.TileLayer('Esri.WorldImagery', name='Satellite').add_to(m)

# Feature loop
for feature in geojson["features"]:
    props = feature.get("properties", {}) or {}
    iso3 = extract_iso3(props)
    rest_obj = None

    # try iso3 lookup first
    if iso3:
        rest_obj = rest_by_cca3.get(str(iso3).upper())

    # fallback by administrative name
    if not rest_obj:
        geo_name = (props.get("ADMIN") or props.get("NAME") or props.get("name") or "").strip()
        if geo_name:
            rest_obj = rest_by_name_lower.get(geo_name.lower())
            if not rest_obj:
                # partial match fallback
                for nm, obj in rest_by_name_lower.items():
                    if geo_name.lower() in nm:
                        rest_obj = obj
                        break

    # display name & basic fields
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

    # languages
    languages = []
    if rest_obj and rest_obj.get("languages"):
        languages = list(rest_obj["languages"].values())

    # flags
    flag_png = None
    if rest_obj and rest_obj.get("flags"):
        # restcountries exposes flags {png, svg}
        flag_png = rest_obj["flags"].get("png") or rest_obj["flags"].get("svg")

    # geometry analytics: area, centroid, bounds
    geom = feature.get("geometry")
    area_sqkm = "—"
    centroid_lat = centroid_lon = "—"
    bbox_str = "—"
    try:
        poly = shape(geom)
        # compute centroid lat/lon (in degrees)
        centroid = poly.centroid
        centroid_lon = round(centroid.x, 6)
        centroid_lat = round(centroid.y, 6)
        bounds = poly.bounds  # (minx, miny, maxx, maxy)
        bbox_str = bbox_to_string(bounds)

        # project to equal-area and compute area
        try:
            projected = shapely_transform(transformer.transform, poly)
            area_m2 = projected.area
            area_sqkm = round(area_m2 / 1e6, 2)
        except Exception:
            # fallback: compute geodesic approx via WebMercator if transform fails
            fallback_transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            proj2 = shapely_transform(fallback_transformer.transform, poly)
            area_m2 = proj2.area
            area_sqkm = round(area_m2 / 1e6, 2)
    except Exception as e:
        # keep defaults
        area_sqkm = "—"
        centroid_lat = centroid_lon = "—"
        bbox_str = "—"

    # build popup HTML (compact and readable)
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

    # add feature with popup
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

# Add layer control
folium.LayerControl(position='topright').add_to(m)

# render and embed
map_html = m.get_root().render()
components.v1.html(map_html, height=760, scrolling=True)

# small footer
st.markdown("---")
st.markdown(f"Note: area computed by projecting to {used_crs} (equal-area preference). Values are approximate.")
