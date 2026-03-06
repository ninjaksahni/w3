import re
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

st.set_page_config(page_title="Amazon Warehouse Stock", layout="wide")

# ── City name lookup ──────────────────────────────────────────────────────────
CITY_NAMES = {
    "DEL": "Delhi",
    "BOM": "Mumbai",
    "BLR": "Bangalore",
    "MAA": "Chennai",
    "HYD": "Hyderabad",
    "CCU": "Kolkata",
    "AMD": "Ahmedabad",
    "PNQ": "Pune",
    "JAI": "Jaipur",
    "LKO": "Lucknow",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

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
    """Strip trailing digits: DEL4 → DEL"""
    return re.sub(r"\d+$", "", str(location)).strip().upper()


def city_display_name(code: str) -> str:
    return CITY_NAMES.get(code, code)


@st.cache_data(show_spinner=False)
def generate_pdf_report(agg_df_json, city_df_json, damaged_df_json, timestamp):
    agg_df     = pd.read_json(agg_df_json)
    city_df    = pd.read_json(city_df_json)
    damaged_df = pd.read_json(damaged_df_json)

    buffer = BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SectionTitle", fontSize=13, leading=16, spaceAfter=6,
        textColor=colors.darkblue, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(name="NormalSmall", fontSize=10, leading=12))

    elements = []
    elements.append(Paragraph("Amazon Warehouse Stock Report", styles["Title"]))
    elements.append(Paragraph(f"Generated on: {timestamp}", styles["Normal"]))
    elements.append(Spacer(1, 16))

    # ── Damaged stock ────────────────────────────────────────────────────────
    if not damaged_df.empty:
        elements.append(Paragraph("⚠️ Damaged / Non-Sellable Stock", styles["SectionTitle"]))
        elements.append(Spacer(1, 6))
        data = [["MSKU", "Title", "Disposition", "Units", "Location"]]
        for _, row in damaged_df.iterrows():
            data.append([
                row["MSKU"],
                str(row.get("Title", ""))[:60],
                row["Disposition"],
                int(row["Ending Warehouse Balance"]),
                row["Location"],
            ])
        table = Table(data, colWidths=[60, 180, 110, 50, 60])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.orangered),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 14))

    # ── City summary ─────────────────────────────────────────────────────────
    elements.append(Paragraph("📍 Units Per SKU Per City", styles["SectionTitle"]))
    elements.append(Spacer(1, 6))
    for city_code, city_grp in city_df.groupby("CityCode"):
        label = f"{city_display_name(city_code)} ({city_code})"
        elements.append(Paragraph(f"🏙️ {label}", styles["SectionTitle"]))
        data = [["MSKU", "Title", "Total Units"]]
        for _, row in city_grp.sort_values("Ending Warehouse Balance", ascending=False).iterrows():
            data.append([row["MSKU"], str(row.get("Title", ""))[:55], int(row["Ending Warehouse Balance"])])
        table = Table(data, colWidths=[60, 280, 80])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.steelblue),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (2, 1), (2, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    elements.append(Spacer(1, 10))

    # ── Warehouse detail ─────────────────────────────────────────────────────
    elements.append(Paragraph("🏬 Stock By Warehouse", styles["SectionTitle"]))
    elements.append(Spacer(1, 6))
    for location, loc_df in agg_df.groupby("Location"):
        elements.append(Paragraph(f"🏬 {location}", styles["SectionTitle"]))
        data = [["MSKU", "Title", "In Transit", "Sellable Units"]]
        for _, row in loc_df.iterrows():
            data.append([
                row["MSKU"],
                str(row.get("Title", ""))[:55],
                int(row.get("In Transit Between Warehouses", 0)),
                int(row["Ending Warehouse Balance"]),
            ])
        table = Table(data, colWidths=[60, 250, 70, 80])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (2, 1), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


# ── Page header ───────────────────────────────────────────────────────────────
st.title("📦 Amazon Warehouse Stock")
st.markdown(
    """
**Step 1 — Download:** Get the Ledger Report CSV from Amazon Seller Central for the **last 2 days excluding today**:  
https://sellercentral.amazon.in/reportcentral/LEDGER_REPORT/1  
**Step 2 — Upload:** Upload the downloaded CSV below.
"""
)

uploaded_file = st.file_uploader("📤 Upload Ledger CSV", type=["csv"])

# ── Main ──────────────────────────────────────────────────────────────────────
if uploaded_file:
    try:
        df = _read_csv_safe(uploaded_file)
    except Exception as e:
        st.error(f"Could not read uploaded file: {e}")
        st.stop()

    df.columns = [c.strip() for c in df.columns]

    required = {
        "msku":     "MSKU",
        "disposition": "Disposition",
        "balance":  "Ending Warehouse Balance",
        "location": "Location",
    }
    found = {}
    for key, pretty in required.items():
        col = _find_col(df, pretty) or _find_col(df, key)
        found[key] = col

    missing = [v for k, v in required.items() if found[k] is None]
    if missing:
        st.error(
            f"CSV is missing required columns: {missing}\n"
            f"Found columns: {list(df.columns)}"
        )
        st.stop()

    msku_col = found["msku"]
    disp_col = found["disposition"]
    bal_col  = found["balance"]
    loc_col  = found["location"]
    title_col = _find_col(df, "Title")
    transit_col = _find_col(df, "In Transit Between Warehouses")

    # Clean balance
    df[bal_col] = (
        df[bal_col].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(r"[^\d.\-]", "", regex=True)
    )
    df[bal_col] = pd.to_numeric(df[bal_col], errors="coerce").fillna(0).astype(int)
    df[disp_col] = df[disp_col].astype(str).str.strip().str.upper()
    df[loc_col]  = df[loc_col].fillna("Unknown")

    # ── Damaged / non-sellable ────────────────────────────────────────────────
    sellable_dispositions = {"SELLABLE"}
    df_damaged = df[~df[disp_col].isin(sellable_dispositions) & (df[bal_col] > 0)].copy()

    # ── Sellable only, balance > 0 ────────────────────────────────────────────
    df_sellable = df[df[disp_col].isin(sellable_dispositions) & (df[bal_col] > 0)].copy()

    if df_sellable.empty:
        st.warning("No SELLABLE items with a positive balance found in this file.")
        st.stop()

    # ── Aggregate sellable by location + MSKU ────────────────────────────────
    group_cols = [loc_col, msku_col]
    if title_col:
        group_cols.append(title_col)

    agg_parts = {bal_col: "sum"}
    if transit_col:
        agg_parts[transit_col] = "sum"

    agg = (
        df_sellable
        .groupby(group_cols, as_index=False)
        .agg(agg_parts)
    )
    rename_map = {loc_col: "Location", msku_col: "MSKU", bal_col: "Ending Warehouse Balance"}
    if title_col:
        rename_map[title_col] = "Title"
    if transit_col:
        rename_map[transit_col] = "In Transit Between Warehouses"
    agg.rename(columns=rename_map, inplace=True)

    # ── Movement / velocity ───────────────────────────────────────────────────
    ship_col   = _find_col(df, "Customer Shipments")
    start_col  = _find_col(df, "Starting Warehouse Balance")
    receipt_col = _find_col(df, "Receipts")

    velocity = None
    if ship_col:
        vel = (
            df_sellable.groupby(msku_col, as_index=False)[ship_col]
            .sum()
            .rename(columns={msku_col: "MSKU", ship_col: "Units Sold"})
        )
        vel["Units Sold"] = vel["Units Sold"].abs()
        velocity = vel

    # ── City aggregation ──────────────────────────────────────────────────────
    agg["CityCode"] = agg["Location"].apply(extract_city_code)

    city_group_cols = ["CityCode", "MSKU"]
    if "Title" in agg.columns:
        city_group_cols.append("Title")

    city_agg_parts = {"Ending Warehouse Balance": "sum"}
    if "In Transit Between Warehouses" in agg.columns:
        city_agg_parts["In Transit Between Warehouses"] = "sum"

    city_agg = agg.groupby(city_group_cols, as_index=False).agg(city_agg_parts)

    # ── Summary metrics ───────────────────────────────────────────────────────
    location_totals = agg.groupby("Location")["Ending Warehouse Balance"].sum().sort_values(ascending=False)
    locations       = list(location_totals.index)
    total_warehouses = len(locations)
    unique_skus      = agg["MSKU"].nunique()
    overall_total    = int(agg["Ending Warehouse Balance"].sum())
    total_damaged    = int(df_damaged[bal_col].sum()) if not df_damaged.empty else 0
    total_in_transit = int(agg["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in agg.columns else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Warehouses",         total_warehouses)
    c2.metric("Unique MSKUs",       unique_skus)
    c3.metric("Total Sellable Qty", overall_total)
    c4.metric("In Transit",         total_in_transit)
    c5.metric("⚠️ Damaged Units",   total_damaged, delta_color="inverse")

    st.markdown("---")

    # ── Damaged stock warning ─────────────────────────────────────────────────
    if not df_damaged.empty:
        with st.expander(f"⚠️ Damaged / Non-Sellable Stock — {total_damaged} units", expanded=True):
            dam_display = df_damaged[[msku_col, title_col if title_col else msku_col, disp_col, bal_col, loc_col]].copy()
            dam_display.columns = ["MSKU", "Title", "Disposition", "Units", "Location"] if title_col else ["MSKU", "MSKU", "Disposition", "Units", "Location"]
            dam_display = dam_display.sort_values("Units", ascending=False).reset_index(drop=True)
            st.dataframe(dam_display, use_container_width=True, hide_index=True)

        st.markdown("---")

    # ── Velocity / movement table ─────────────────────────────────────────────
    if velocity is not None and not velocity.empty:
        with st.expander("📈 Units Sold This Period (by MSKU)", expanded=False):
            vel_display = velocity.sort_values("Units Sold", ascending=False).reset_index(drop=True)
            if "Title" in agg.columns:
                title_map = agg.drop_duplicates("MSKU").set_index("MSKU")["Title"]
                vel_display["Title"] = vel_display["MSKU"].map(title_map)
            st.dataframe(vel_display, use_container_width=True, hide_index=True)

        st.markdown("---")

    # ════════════════════════════════════════
    # CITY SUMMARY
    # ════════════════════════════════════════
    st.subheader("🏙️ Units Per SKU Per City")
    city_totals = city_agg.groupby("CityCode")["Ending Warehouse Balance"].sum().sort_values(ascending=False)
    cities      = list(city_totals.index)

    for city_chunk in chunks(cities, 3):
        cols = st.columns(3)
        for i, city_code in enumerate(city_chunk):
            with cols[i]:
                cdf = city_agg[city_agg["CityCode"] == city_code].sort_values(
                    by="Ending Warehouse Balance", ascending=False
                ).reset_index(drop=True)
                city_total    = int(cdf["Ending Warehouse Balance"].sum())
                city_transit  = int(cdf["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in cdf.columns else 0
                display_name  = city_display_name(city_code)

                col_h1, col_h2 = st.columns([0.7, 0.3])
                with col_h1:
                    st.markdown(f"### 🏙️ **{display_name}**")
                    st.caption(f"Sellable: **{city_total}** · In Transit: **{city_transit}**")
                with col_h2:
                    st.download_button(
                        label="⬇️ CSV",
                        data=cdf.to_csv(index=False).encode("utf-8"),
                        file_name=f"{city_code}_city_sellable.csv",
                        mime="text/csv",
                        key=f"dl_city_{city_code}",
                    )

                for _, row in cdf.iterrows():
                    title_text = f" — *{str(row['Title'])[:40]}*" if "Title" in cdf.columns else ""
                    st.markdown(
                        f"- 📦 **{row['MSKU']}** — {int(row['Ending Warehouse Balance'])} units{title_text}"
                    )

    st.markdown("---")

    # ════════════════════════════════════════
    # WAREHOUSE CARDS — with search
    # ════════════════════════════════════════
    st.subheader("🏬 Stock By Warehouse")
    search = st.text_input("🔍 Filter by MSKU or Title", value="").strip().lower()

    filtered_agg = agg.copy()
    if search:
        mask = filtered_agg["MSKU"].astype(str).str.lower().str.contains(search)
        if "Title" in filtered_agg.columns:
            mask = mask | filtered_agg["Title"].astype(str).str.lower().str.contains(search)
        filtered_agg    = filtered_agg[mask]
        location_totals = filtered_agg.groupby("Location")["Ending Warehouse Balance"].sum().sort_values(ascending=False)
        locations       = list(location_totals.index)

    if filtered_agg.empty:
        st.info("No results match your filter.")
    else:
        for chunk in chunks(locations, 3):
            cols = st.columns(3)
            for i, loc in enumerate(chunk):
                with cols[i]:
                    loc_df    = filtered_agg[filtered_agg["Location"] == loc].sort_values(
                        by="Ending Warehouse Balance", ascending=False
                    ).reset_index(drop=True)
                    loc_total   = int(loc_df["Ending Warehouse Balance"].sum())
                    loc_transit = int(loc_df["In Transit Between Warehouses"].sum()) if "In Transit Between Warehouses" in loc_df.columns else 0

                    col_h1, col_h2 = st.columns([0.7, 0.3])
                    with col_h1:
                        st.markdown(f"### 🏬 **{loc}**")
                        st.caption(f"Sellable: **{loc_total}** · In Transit: **{loc_transit}**")
                    with col_h2:
                        st.download_button(
                            label="⬇️ CSV",
                            data=loc_df.to_csv(index=False).encode("utf-8"),
                            file_name=f"{loc.replace(' ', '_')}_sellable.csv",
                            mime="text/csv",
                            key=f"dl_{loc}",
                        )

                    for _, row in loc_df.iterrows():
                        title_text = f"\n  *{str(row['Title'])[:45]}*" if "Title" in loc_df.columns else ""
                        transit_text = f" · 🚚 {int(row['In Transit Between Warehouses'])} in transit" if "In Transit Between Warehouses" in loc_df.columns and int(row["In Transit Between Warehouses"]) > 0 else ""
                        st.markdown(
                            f"- 📦 **{row['MSKU']}** — {int(row['Ending Warehouse Balance'])} units{transit_text}{title_text}"
                        )

    st.markdown("---")

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.download_button(
        label="⬇️ Download full aggregated CSV",
        data=agg.to_csv(index=False).encode("utf-8"),
        file_name="aggregated_sellable_by_location_msku.csv",
        mime="text/csv",
    )

    st.markdown("### 📄 Download PDF Report")
    if st.button("Generate PDF"):
        with st.spinner("Building PDF…"):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Prep damaged df for PDF
            if not df_damaged.empty:
                dam_pdf = df_damaged[[msku_col, disp_col, bal_col, loc_col]].copy()
                dam_pdf.columns = ["MSKU", "Disposition", "Ending Warehouse Balance", "Location"]
                if title_col:
                    dam_pdf["Title"] = df_damaged[title_col].values
                else:
                    dam_pdf["Title"] = ""
            else:
                dam_pdf = pd.DataFrame(columns=["MSKU", "Disposition", "Ending Warehouse Balance", "Location", "Title"])

            pdf_bytes = generate_pdf_report(
                agg.to_json(),
                city_agg.to_json(),
                dam_pdf.to_json(),
                timestamp,
            )

        st.download_button(
            label="⬇️ Download PDF",
            data=pdf_bytes,
            file_name=f"warehouse_stock_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
        )
