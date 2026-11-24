import io
import json
import mimetypes
import os
import re
import time
import zipfile
from datetime import datetime
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from docx import Document
from dotenv import load_dotenv
from fpdf import FPDF
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ==========================================
# 1. CONFIGURATION & WHITE-LABEL SECRETS
# ==========================================
load_dotenv()


def get_config(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


APP_BRAND_NAME = get_config("APP_BRAND_NAME", "WebExtract Studio")
APP_TAGLINE = get_config("APP_TAGLINE", "Universal Web Scraper & Multi-Format Export Engine")
APP_ACCENT_COLOR = get_config("APP_ACCENT_COLOR", "#2563EB")
ACCESS_PASSWORD = get_config("DASHBOARD_ACCESS_PASSWORD", "AsifAdmin@2026")

st.set_page_config(page_title=APP_BRAND_NAME, page_icon="🕸️", layout="wide")


def inject_custom_css():
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
    custom_css = ""
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            custom_css = f.read()

    st.markdown(
        f"""
        <style>
        :root {{
            --accent-color: {APP_ACCENT_COLOR};
        }}
        {custom_css}
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_custom_css()


# ==========================================
# 2. PRIVATE LOGIN GATE
# ==========================================
def check_authentication() -> bool:
    if st.session_state.get("authenticated", False):
        return True

    _, center_col, _ = st.columns([1, 1.4, 1])
    with center_col:
        st.markdown(f"<div class='brand-header'><h1>🕸️ {APP_BRAND_NAME}</h1><p>{APP_TAGLINE}</p></div>", unsafe_allow_html=True)
        with st.form("login_form"):
            pwd = st.text_input("Workspace Access Password", type="password", placeholder="Enter access password")
            submitted = st.form_submit_button("Unlock Studio", use_container_width=True)
            if submitted:
                if pwd == ACCESS_PASSWORD:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("Incorrect access password.")
    return False


if not check_authentication():
    st.stop()


# ==========================================
# 3. FOOL-PROOF SCRAPING ENGINE
# ==========================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

BOT_GATE_PHRASES = [
    "click the button below to continue shopping",
    "type the characters you see in this image",
    "enter the characters you see below",
    "sorry, we just need to make sure you're not a robot",
    "enable javascript and cookies to continue",
    "verify you are human",
    "checking your browser before accessing",
]


def is_blocked_content(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered) < 220:
        return True
    return any(phrase in lowered for phrase in BOT_GATE_PHRASES)


def fetch_via_http(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Upgrade-Insecure-Requests": "1",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text, ""


def bypass_interstitial_gates(driver):
    """Automatically click 'Continue shopping' or cookie consent buttons if present."""
    gate_xpaths = [
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue shopping')]",
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue shopping')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'i agree')]",
    ]
    for xp in gate_xpaths:
        try:
            btns = driver.find_elements(By.XPATH, xp)
            for b in btns:
                if b.is_displayed():
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(3)
                    return
        except Exception:
            continue


def fetch_via_browser(url: str, headless: bool = True) -> tuple[str, str]:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(options=options)
    try:
        # Mask navigator.webdriver before loading target page
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        driver.get(url)
        time.sleep(3)

        # Clear Amazon 'Continue shopping' or GDPR cookie gates if shown
        bypass_interstitial_gates(driver)

        # Scroll down in stages to render lazy-loaded items and images
        for ratio in (0.3, 0.65, 1.0):
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {ratio});")
            time.sleep(1.2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.8)

        rendered_inner_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
        return driver.page_source, rendered_inner_text
    finally:
        driver.quit()


def parse_webpage(html: str, base_url: str, rendered_inner_text: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "Scraped_Page"

    # 1. Extract all images (img tags, lazy attributes, srcset, CSS background URLs, og:image)
    image_rows = []
    seen_imgs = set()
    skip_tokens = ("pixel", "1x1", "spacer", "transparent-pixel", "sprite", "beacon", "blank.gif", "doubleclick")

    def register_image(raw_src: str, label: str):
        if not raw_src or raw_src.startswith("data:"):
            return
        full_url = urljoin(base_url, raw_src.strip())
        low = full_url.lower()
        if not full_url.startswith("http") or any(t in low for t in skip_tokens) or full_url in seen_imgs:
            return
        seen_imgs.add(full_url)
        image_rows.append({"Alt / Label": (label.strip() or "Page Image")[:120], "Image URL": full_url})

    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        register_image(og_img["content"], "Featured Social Image (og:image)")

    for img in soup.find_all("img"):
        src = (
            img.get("data-old-hires")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or img.get("src")
            or ""
        )
        if not src and img.get("srcset"):
            parts = [p.strip().split(" ")[0] for p in img["srcset"].split(",") if p.strip()]
            if parts:
                src = parts[-1]
        register_image(src, img.get("alt") or img.get("title") or "Page Image")

    # Also capture CSS inline background-image URLs (common in modern hero banners & product cards)
    for tag in soup.find_all(style=True):
        bg_matches = re.findall(r"url\(['\"]?(https?://[^'\"\)]+)['\"]?\)", tag["style"])
        for bg_url in bg_matches:
            register_image(bg_url, "Background Graphic")

    # 2. Extract all unique HTTP links
    link_rows = []
    seen_links = set()
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        full_href = urljoin(base_url, a["href"])
        if full_href.startswith("http") and full_href not in seen_links:
            seen_links.add(full_href)
            link_rows.append({"Anchor Text": (label or full_href)[:120], "URL": full_href})

    # 3. Extract HTML tables
    tables = []
    for tbl in soup.find_all("table"):
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if len(rows) > 1:
            max_cols = max(len(r) for r in rows)
            padded = [r + [""] * (max_cols - len(r)) for r in rows]
            tables.append(pd.DataFrame(padded[1:], columns=padded[0]))

    # 4. Extract emails
    emails = sorted(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)))

    # 5. Extract clean readable text (prefer live rendered browser innerText when available)
    if rendered_inner_text and len(rendered_inner_text.strip()) > 150:
        raw_lines = rendered_inner_text.splitlines()
    else:
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        root = soup.body if soup.body else soup
        raw_lines = root.get_text(separator="\n").splitlines()

    clean_lines = []
    seen_lines = set()
    for line in raw_lines:
        norm = re.sub(r"\s+", " ", line).strip()
        if len(norm) < 2:
            continue
        if norm not in seen_lines:
            seen_lines.add(norm)
            clean_lines.append(norm)

    return {
        "title": title,
        "text": "\n".join(clean_lines),
        "emails": emails,
        "links_df": pd.DataFrame(link_rows),
        "images_df": pd.DataFrame(image_rows),
        "tables": tables,
    }


def smart_scrape(url: str, mode: str) -> tuple[dict, str]:
    if mode == "Instant (HTTP)":
        html, _ = fetch_via_http(url)
        return parse_webpage(html, url), "Instant (HTTP)"

    if mode == "Dynamic JS (Chrome)":
        html, inner_txt = fetch_via_browser(url, headless=True)
        parsed = parse_webpage(html, url, inner_txt)
        if is_blocked_content(parsed["text"]):
            html, inner_txt = fetch_via_browser(url, headless=False)
            parsed = parse_webpage(html, url, inner_txt)
            return parsed, "Dynamic JS (Visible Chrome Bypass)"
        return parsed, "Dynamic JS (Headless Chrome)"

    # Auto (Smart): Step 1 -> Fast HTTP | Step 2 -> Headless Chrome | Step 3 -> Visible Chrome
    try:
        html, _ = fetch_via_http(url)
        parsed = parse_webpage(html, url)
        if not is_blocked_content(parsed["text"]):
            return parsed, "Instant (HTTP)"
    except Exception:
        pass

    html, inner_txt = fetch_via_browser(url, headless=True)
    parsed = parse_webpage(html, url, inner_txt)
    if is_blocked_content(parsed["text"]):
        html, inner_txt = fetch_via_browser(url, headless=False)
        parsed = parse_webpage(html, url, inner_txt)
        return parsed, "Auto-Escalated (Visible Chrome Bypass)"

    return parsed, "Auto-Escalated (Headless Chrome)"


# ==========================================
# 4. MULTI-FORMAT EXPORTERS (DOCX, PDF, ZIP)
# ==========================================
def build_docx_bytes(title: str, url: str, body_text: str, images_df: pd.DataFrame) -> bytes:
    doc = Document()
    doc.add_heading(title, level=1)
    doc.add_paragraph(f"Source URL: {url}")
    doc.add_paragraph(f"Scraped On: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph("-" * 50)

    for line in body_text.splitlines():
        if line.strip():
            doc.add_paragraph(line.strip())

    if not images_df.empty:
        doc.add_page_break()
        doc.add_heading(f"Extracted Images ({len(images_df)})", level=2)
        for idx, row in images_df.iterrows():
            doc.add_paragraph(f"{idx + 1}. {row['Alt / Label']} — {row['Image URL']}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_pdf_bytes(title: str, url: str, body_text: str, images_df: pd.DataFrame) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    full_content = body_text
    if not images_df.empty:
        img_lines = "\n".join(
            f"{i + 1}. {r['Alt / Label']}: {r['Image URL']}" for i, r in images_df.iterrows()
        )
        full_content += f"\n\n--- EXTRACTED IMAGES ({len(images_df)}) ---\n{img_lines}"

    safe_title = title.encode("latin-1", "replace").decode("latin-1")
    safe_url = url.encode("latin-1", "replace").decode("latin-1")
    safe_body = full_content.encode("latin-1", "replace").decode("latin-1")

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 15)
    pdf.multi_cell(pdf.epw, 8, safe_title, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        pdf.epw,
        5,
        f"Source: {safe_url} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        new_x="LMARGIN",
        new_y="NEXT",
        wrapmode="CHAR",
    )
    pdf.ln(4)

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(pdf.epw, 5.5, safe_body, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    return bytes(pdf.output())


def build_images_zip(images_df: pd.DataFrame, max_images: int = 30) -> bytes:
    buf = io.BytesIO()
    headers = {"User-Agent": USER_AGENT}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, row in images_df.head(max_images).iterrows():
            img_url = row["Image URL"]
            try:
                r = requests.get(img_url, headers=headers, timeout=6)
                if r.status_code == 200 and r.content:
                    ctype = r.headers.get("Content-Type", "")
                    ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ""
                    if not ext:
                        path_ext = "." + urlparse(img_url).path.split(".")[-1].lower()
                        ext = path_ext if path_ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"
                    zf.writestr(f"image_{idx + 1:02d}{ext}", r.content)
            except Exception:
                continue
    return buf.getvalue()


def render_copy_button(text_to_copy: str):
    escaped = json.dumps(text_to_copy)
    components.html(
        f"""
        <button onclick='
            navigator.clipboard.writeText({escaped});
            this.innerText = "✅ Copied to Clipboard!";
            setTimeout(() => this.innerText = "📋 Copy Text to Clipboard", 2000);
        ' style="
            background-color: {APP_ACCENT_COLOR};
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        ">📋 Copy Text to Clipboard</button>
        """,
        height=48,
    )


# ==========================================
# 5. MAIN DASHBOARD UI
# ==========================================
top_left, top_right = st.columns([5, 1])
with top_left:
    st.markdown(f"<div class='brand-header'><h1>🕸️ {APP_BRAND_NAME}</h1><p>{APP_TAGLINE}</p></div>", unsafe_allow_html=True)
with top_right:
    st.write("")
    if st.button("🔒 Lock", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

with st.container(border=True):
    col_url, col_mode, col_btn = st.columns([3.0, 1.4, 1.0])
    with col_url:
        target_url = st.text_input("Target Website URL", placeholder="https://www.amazon.in/ or any website link")
    with col_mode:
        engine_mode = st.selectbox(
            "Scraper Engine",
            ["Auto (Smart)", "Instant (HTTP)", "Dynamic JS (Chrome)"],
        )
    with col_btn:
        st.write("")
        st.write("")
        run_scrape = st.button("⚡ Scrape Now", type="primary", use_container_width=True)

    with st.expander("ℹ️ Difference Between Instant (HTTP) vs. Dynamic JS (Chrome)", expanded=False):
        g1, g2, g3 = st.columns(3)
        with g1:
            st.markdown("**⚡ Instant (HTTP)**")
            st.caption(
                "Downloads raw HTML in ~0.5s without opening Chrome. "
                "Ideal for **blogs, news articles, Wikipedia, and static sites**."
            )
        with g2:
            st.markdown("**🌐 Dynamic JS (Chrome)**")
            st.caption(
                "Opens real Chrome, bypasses 'Continue shopping' gates, executes JavaScript, and scrolls the page. "
                "Required for **Amazon, e-commerce stores, React/Next.js apps, and lazy-loaded images**."
            )
        with g3:
            st.markdown("**🧠 Auto (Smart — Recommended)**")
            st.caption(
                "Tries **Instant (HTTP)** first. If blocked or empty, automatically escalates to **Headless Chrome**, "
                "and if still gated, opens **Visible Chrome** to extract the full live page."
            )

if run_scrape:
    clean_url = target_url.strip()
    if not clean_url.startswith("http"):
        st.error("Please enter a valid URL starting with http:// or https://")
    else:
        with st.spinner("Extracting text, images, tables, and links..."):
            try:
                parsed_result, used_engine = smart_scrape(clean_url, engine_mode)
                st.session_state["scraped_data"] = parsed_result
                st.session_state["scraped_url"] = clean_url
                st.session_state["used_engine"] = used_engine
                # Explicitly sync text area state so every new scrape updates the text box immediately
                st.session_state["edited_text"] = parsed_result["text"]
            except Exception as exc:
                st.error(f"Scraping failed: {exc}")

if "scraped_data" in st.session_state:
    data = st.session_state["scraped_data"]
    src_url = st.session_state["scraped_url"]
    used_engine = st.session_state.get("used_engine", engine_mode)

    st.success(f"✅ Scraped **{data['title']}** via **{used_engine}**")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Characters Extracted", f"{len(data['text']):,}")
    m2.metric("Images Found", len(data["images_df"]))
    m3.metric("Links Found", len(data["links_df"]))
    m4.metric("Emails Found", len(data["emails"]))

    tab_text, tab_images, tab_links = st.tabs([
        "📝 Extracted Text & Exports",
        f"🖼️ Scraped Images ({len(data['images_df'])})",
        f"🔗 Links & Tables ({len(data['links_df'])})",
    ])

    with tab_text:
        st.subheader("1. Extracted Content Box")
        current_text = st.session_state.get("edited_text", data["text"])
        render_copy_button(current_text)
        st.text_area(
            "Scraped Text (Editable before exporting)",
            height=320,
            key="edited_text",
        )

        st.subheader("2. Download in Your Preferred Format")
        final_text = st.session_state.get("edited_text", data["text"])
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", data["title"])[:40] or "scraped_output"

        c_docx, c_pdf, c_csv = st.columns(3)
        with c_docx:
            st.download_button(
                "📘 Download Word (.docx)",
                data=build_docx_bytes(data["title"], src_url, final_text, data["images_df"]),
                file_name=f"{safe_slug}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        with c_pdf:
            st.download_button(
                "📕 Download PDF (.pdf)",
                data=build_pdf_bytes(data["title"], src_url, final_text, data["images_df"]),
                file_name=f"{safe_slug}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        with c_csv:
            csv_df = data["tables"][0] if data["tables"] else data["links_df"]
            st.download_button(
                "📗 Download Table/Links (.csv)",
                data=csv_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{safe_slug}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if data["emails"]:
            st.info("**Emails Detected:** " + ", ".join(data["emails"]))

    with tab_images:
        if data["images_df"].empty:
            st.warning("No images detected on this page.")
        else:
            safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", data["title"])[:40] or "scraped_output"
            b1, b2 = st.columns(2)
            with b1:
                st.download_button(
                    "📦 Download Top 30 Images (.zip)",
                    data=build_images_zip(data["images_df"], max_images=30),
                    file_name=f"{safe_slug}_images.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True,
                )
            with b2:
                st.download_button(
                    "📄 Download Image URLs (.csv)",
                    data=data["images_df"].to_csv(index=False).encode("utf-8"),
                    file_name=f"{safe_slug}_image_urls.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            st.subheader("Visual Gallery Preview (First 12 Images)")
            cols = st.columns(4)
            for idx, row in data["images_df"].head(12).iterrows():
                with cols[idx % 4]:
                    st.image(row["Image URL"], caption=row["Alt / Label"][:45], use_container_width=True)

            st.subheader("All Scraped Image URLs")
            st.dataframe(data["images_df"], use_container_width=True, hide_index=True)

    with tab_links:
        if data["tables"]:
            st.subheader("Detected HTML Tables")
            for t_idx, tbl_df in enumerate(data["tables"]):
                st.write(f"**Table {t_idx + 1}**")
                st.dataframe(tbl_df, use_container_width=True, hide_index=True)
        st.subheader("Extracted Page Links")
        st.dataframe(data["links_df"], use_container_width=True, hide_index=True)