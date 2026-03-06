import re
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Amazon Warehouse Stock", layout="wide")

CITY_NAMES = {
    "DEL": "Delhi", "BOM": "Mumbai", "BLR": "Bangalore",
    "MAA": "Chennai", "HYD": "Hyderabad", "CCU": "Kolkata",
    "AMD": "Ahmedabad", "PNQ": "Pune", "JAI": "Jaipur", "LKO": "Lucknow",
}

def _read_csv_safe(uploaded_file):
    uploaded_file.seek(0)
    for enc in (None, "latin1", "utf-8"):
        try:
            if enc:
                return pd.read_csv(uploaded_file, encoding=enc)
            return pd.read_csv(uploaded_file)
        except Exception:
            uploaded_file.seek(0)
    uploaded_file.seek(0)
    return pd.read_csv(uploaded_file, engine="python", encoding="utf-8", on_bad_lines="skip")

def _find_col(df, name):
    mapping = {c.strip().lower(): c for c in df.columns}
    return mapping.get(name.strip().lower())

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

def extract_city_code(location: str) -> str:
    return re.sub(r"\d+$", "", str(location)).strip().upper()

def city_display_name(code: str) -> str:
    return CITY_NAMES.get(code, code)

def generate_html_report(agg_df, city_agg, timestamp):
    def tbl(headers, rows, hcolor="#2c6fad"):
        cols = "".join(f"<th>{h}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        return f'<table><thead style="background:{hcolor};color:white"><tr>{cols}</tr></thead><tbody>{body}</tbody></table>'

    css = """<style>
body{font-family:Arial,sans-serif;font-size:13px;color:#222;margin:24px}
h1{color:#1a3e6e}h2{color:#2c6fad;border-bottom:2px solid #2c6fad;padding-bottom:4px;margin-top:32px}
h3{color:#444;margin-bottom:4px}
table{border-collapse:collapse;width:100%;margin-bottom:20px}
th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}
tr:nth-child(even){background:#f5f8fc}
</style>"""

    html = f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Warehouse Stock Report</title>{css}</head><body>'
    html += f'<h1>Amazon Warehouse Stock Report</h1><p>Generated: <strong>{timestamp}</strong></p>'

    html += "<h2>Units Per SKU Per City</h2>"
    for city_code, grp in city_agg.groupby("CityCode"):
        name  = city_display_name(city_code)
        total = int(grp["Ending Warehouse Balance"].sum())
        html += f"<h3>{name} ({city_code}) — {total} units</h3>"
        rows  = [[r["MSKU"], int(r["Ending Warehouse Balance"])]
                 for _, r in grp.sort_values("Ending Warehouse Balance", ascending=False).iterrows()]
        html += tbl(["MSKU", "Units"], rows)

    html += "<h2>Stock By Warehouse</h2>"
    for location, grp in agg_df.groupby("Location"):
        total   = int(grp["Ending Warehouse Balance"].sum())
        transit = int(grp["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in grp.columns else 0
        html += f"<h3>{location} — {total} sellable · {transit} in transit</h3>"
        rows = [[r["MSKU"],
                 int(r.get("In Transit Between Warehouses", 0)),
                 int(r["Ending Warehouse Balance"])]
                for _, r in grp.sort_values("Ending Warehouse Balance", ascending=False).iterrows()]
        html += tbl(["MSKU", "In Transit", "Sellable Units"], rows, "#555")

    html += "</body></html>"
    return html.encode("utf-8")


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("📦 Amazon Warehouse Stock")
st.markdown("""
**Step 1 — Download:** Get the Ledger Report CSV from Amazon Seller Central for the **last 2 days excluding today**:  
https://sellercentral.amazon.in/reportcentral/LEDGER_REPORT/1  
**Step 2 — Upload:** Upload the downloaded CSV below.
""")

uploaded_file = st.file_uploader("📤 Upload Ledger CSV", type=["csv"])

if uploaded_file:
    try:
        df = _read_csv_safe(uploaded_file)
    except Exception as e:
        st.error(f"Could not read uploaded file: {e}")
        st.stop()

    df.columns = [c.strip() for c in df.columns]

    required = {"msku": "MSKU", "disposition": "Disposition",
                "balance": "Ending Warehouse Balance", "location": "Location"}
    found = {key: (_find_col(df, pretty) or _find_col(df, key)) for key, pretty in required.items()}

    missing = [pretty for key, pretty in required.items() if found[key] is None]
    if missing:
        st.error(f"CSV is missing required columns: {missing}\nFound: {list(df.columns)}")
        st.stop()

    msku_col    = found["msku"]
    disp_col    = found["disposition"]
    bal_col     = found["balance"]
    loc_col     = found["location"]
    transit_col = _find_col(df, "In Transit Between Warehouses")
    ship_col    = _find_col(df, "Customer Shipments")

    df[bal_col]  = pd.to_numeric(
        df[bal_col].astype(str).str.replace(",", "", regex=False).str.replace(r"[^\d.\-]", "", regex=True),
        errors="coerce"
    ).fillna(0).astype(int)
    df[disp_col] = df[disp_col].astype(str).str.strip().str.upper()
    df[loc_col]  = df[loc_col].fillna("Unknown")

    df_sellable = df[df[disp_col].isin({"SELLABLE"}) & (df[bal_col] > 0)].copy()

    if df_sellable.empty:
        st.warning("No SELLABLE items with a positive balance found.")
        st.stop()

    group_cols = [loc_col, msku_col]
    agg_parts  = {bal_col: "sum"}
    if transit_col:
        agg_parts[transit_col] = "sum"

    agg = df_sellable.groupby(group_cols, as_index=False).agg(agg_parts)
    rename_map = {loc_col: "Location", msku_col: "MSKU", bal_col: "Ending Warehouse Balance"}
    if transit_col:
        rename_map[transit_col] = "In Transit Between Warehouses"
    agg.rename(columns=rename_map, inplace=True)

    # Velocity
    velocity = None
    if ship_col:
        vel = (
            df_sellable.groupby(msku_col, as_index=False)[ship_col]
            .sum()
            .rename(columns={msku_col: "MSKU", ship_col: "Units Sold"})
        )
        vel["Units Sold"] = vel["Units Sold"].abs()
        velocity = vel

    # City aggregation
    agg["CityCode"] = agg["Location"].apply(extract_city_code)
    city_agg_parts  = {"Ending Warehouse Balance": "sum"}
    if "In Transit Between Warehouses" in agg.columns:
        city_agg_parts["In Transit Between Warehouses"] = "sum"
    city_agg = agg.groupby(["CityCode", "MSKU"], as_index=False).agg(city_agg_parts)

    # Metrics
    location_totals  = agg.groupby("Location")["Ending Warehouse Balance"].sum().sort_values(ascending=False)
    locations        = list(location_totals.index)
    total_in_transit = int(agg["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in agg.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Warehouses",         len(locations))
    c2.metric("Unique MSKUs",       agg["MSKU"].nunique())
    c3.metric("Total Sellable Qty", int(agg["Ending Warehouse Balance"].sum()))
    c4.metric("In Transit",         total_in_transit)
    st.markdown("---")

    # Velocity expander
    if velocity is not None and not velocity.empty:
        with st.expander("📈 Units Sold This Period (by MSKU)", expanded=False):
            st.dataframe(
                velocity.sort_values("Units Sold", ascending=False).reset_index(drop=True),
                use_container_width=True, hide_index=True
            )
        st.markdown("---")

    # ── City cards ───────────────────────────────────────────────────────────
    st.subheader("🏙️ Units Per SKU Per City")
    city_totals = city_agg.groupby("CityCode")["Ending Warehouse Balance"].sum().sort_values(ascending=False)

    for city_chunk in chunks(list(city_totals.index), 3):
        cols = st.columns(3)
        for i, city_code in enumerate(city_chunk):
            with cols[i]:
                cdf          = city_agg[city_agg["CityCode"] == city_code].sort_values("Ending Warehouse Balance", ascending=False).reset_index(drop=True)
                city_total   = int(cdf["Ending Warehouse Balance"].sum())
                city_transit = int(cdf["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in cdf.columns else 0
                col_h1, col_h2 = st.columns([0.7, 0.3])
                with col_h1:
                    st.markdown(f"### 🏙️ **{city_display_name(city_code)}**")
                    st.caption(f"Sellable: **{city_total}** · In Transit: **{city_transit}**")
                with col_h2:
                    st.download_button(
                        label="⬇️ CSV", data=cdf.to_csv(index=False).encode("utf-8"),
                        file_name=f"{city_code}_city_sellable.csv", mime="text/csv",
                        key=f"dl_city_{city_code}",
                    )
                for _, row in cdf.iterrows():
                    st.markdown(f"- 📦 **{row['MSKU']}** — {int(row['Ending Warehouse Balance'])} units")

    st.markdown("---")

    # ── Warehouse cards ──────────────────────────────────────────────────────
    st.subheader("🏬 Stock By Warehouse")
    search = st.text_input("🔍 Filter by MSKU", value="").strip().lower()

    filtered_agg = agg.copy()
    if search:
        filtered_agg    = filtered_agg[filtered_agg["MSKU"].astype(str).str.lower().str.contains(search)]
        location_totals = filtered_agg.groupby("Location")["Ending Warehouse Balance"].sum().sort_values(ascending=False)
        locations       = list(location_totals.index)

    if filtered_agg.empty:
        st.info("No results match your filter.")
    else:
        for chunk in chunks(locations, 3):
            cols = st.columns(3)
            for i, loc in enumerate(chunk):
                with cols[i]:
                    loc_df      = filtered_agg[filtered_agg["Location"] == loc].sort_values("Ending Warehouse Balance", ascending=False).reset_index(drop=True)
                    loc_total   = int(loc_df["Ending Warehouse Balance"].sum())
                    loc_transit = int(loc_df["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in loc_df.columns else 0
                    col_h1, col_h2 = st.columns([0.7, 0.3])
                    with col_h1:
                        st.markdown(f"### 🏬 **{loc}**")
                        st.caption(f"Sellable: **{loc_total}** · In Transit: **{loc_transit}**")
                    with col_h2:
                        st.download_button(
                            label="⬇️ CSV", data=loc_df.to_csv(index=False).encode("utf-8"),
                            file_name=f"{loc.replace(' ', '_')}_sellable.csv", mime="text/csv",
                            key=f"dl_{loc}",
                        )
                    for _, row in loc_df.iterrows():
                        transit_text = f" · 🚚 {int(row['In Transit Between Warehouses'])} in transit" if "In Transit Between Warehouses" in loc_df.columns and int(row["In Transit Between Warehouses"]) > 0 else ""
                        st.markdown(f"- 📦 **{row['MSKU']}** — {int(row['Ending Warehouse Balance'])} units{transit_text}")

    st.markdown("---")

    st.download_button(
        label="⬇️ Download full aggregated CSV",
        data=agg.to_csv(index=False).encode("utf-8"),
        file_name="aggregated_sellable_by_location_msku.csv",
        mime="text/csv",
    )

    st.markdown("### 📄 Download HTML Report")
    st.caption("Open in browser → Ctrl+P / Cmd+P to print or save as PDF.")
    if st.button("Generate Report"):
        with st.spinner("Building report…"):
            timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            html_bytes = generate_html_report(agg, city_agg, timestamp)
        st.download_button(
            label="⬇️ Download HTML Report",
            data=html_bytes,
            file_name=f"warehouse_stock_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
            mime="text/html",
        )
