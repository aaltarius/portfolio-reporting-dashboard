"""
ui/styles.py — Iniezione CSS e JS per la layout dell'app.
"""
import streamlit as st

from ui.streamlit_compat import render_html_iframe
from ui.theme import get_theme_context

def inject_app_styles():
    """Inietta il CSS globale dell'app."""
    theme = get_theme_context()
    surface_alt = theme.colors.get("bg_surface_alt", theme.bg_surface)
    style_css = """<style>
:root{
  --ptf-bg:__PTF_BG__;
  --ptf-surface:__PTF_SURFACE__;
  --ptf-surface-2:__PTF_SURFACE_ALT__;
  --ptf-text:__PTF_TEXT__;
  --ptf-muted:__PTF_MUTED__;
  --ptf-border:__PTF_BORDER__;
  --ptf-primary:__PTF_PRIMARY__;
  --ptf-shadow:__PTF_SHADOW__;
}
html, body, [class*="css"]{
  font-kerning:normal;
}
[data-testid="stAppViewContainer"], .stApp, [data-testid="stMain"], [data-testid="stMainBlockContainer"]{background:var(--ptf-bg)!important;color:var(--ptf-text)!important}
[data-testid="stAppViewContainer"] > .main, .main, .block-container{background:transparent!important}
section[data-testid="stSidebar"], [data-testid="stSidebar"], [data-testid="stSidebarContent"], section[data-testid="stSidebar"] > div:first-child{background:var(--ptf-surface-2)!important;color:var(--ptf-text)!important}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:var(--ptf-text)!important}
.block-container{padding-top:3.35rem;padding-bottom:2.2rem;max-width:1460px}
.summary-help{
  margin-top:6px;
  color:var(--ptf-muted)!important;
  line-height:1.58;
  background:color-mix(in srgb, var(--ptf-primary) 4%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--ptf-text) 10%, transparent);
  border-radius:14px;
  padding:10px 12px;
}
.ptf-insights-shell{
  width:100%;
  box-sizing:border-box;
  margin:4px 0 14px 0;
  background:var(--ptf-surface);
  border:1px solid var(--ptf-border);
  border-radius:16px;
  box-shadow:var(--ptf-shadow);
  overflow:hidden;
}
.ptf-insights-head{
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap:12px;
  padding:11px 14px 10px 14px;
  border-bottom:1px solid var(--ptf-border);
  background:linear-gradient(90deg, rgba(37,99,235,.08), rgba(255,255,255,0));
}
.ptf-insights-eyebrow{
  display:block;
  margin-bottom:2px;
  color:var(--ptf-muted);
  font-size:.70rem;
  font-weight:850;
  letter-spacing:.08em;
  text-transform:uppercase;
}
.ptf-insights-title{
  color:var(--ptf-text);
  font-size:.98rem;
  line-height:1.18;
  font-weight:850;
}
.ptf-insights-sync{
  display:inline-flex;
  align-items:center;
  gap:6px;
  color:var(--ptf-primary);
  font-size:.72rem;
  font-weight:800;
  white-space:nowrap;
  padding:4px 9px;
  border-radius:999px;
  border:1px solid color-mix(in srgb, var(--ptf-primary) 22%, transparent);
  background:color-mix(in srgb, var(--ptf-primary) 7%, var(--ptf-surface));
}
.ptf-insights-sync::before{
  content:"";
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--ptf-primary);
  box-shadow:0 0 0 3px rgba(37,99,235,.12);
}
.ptf-insights-grid{
  display:grid;
  grid-template-columns:repeat(3, minmax(0,1fr));
  gap:10px;
  padding:14px 16px;
}
.ptf-insight-cell{
  --tone:var(--ptf-primary);
  min-width:0;
  display:flex;
  flex-direction:column;
  gap:6px;
  padding:10px 12px;
  border-left:3px solid var(--tone);
  border-radius:12px;
  background:color-mix(in srgb, var(--tone) 5%, var(--ptf-surface));
}
.ptf-insight-cell.is-warning{--tone:var(--ptf-warning, #d97706)}
.ptf-insight-cell.is-critical{--tone:var(--ptf-danger, #dc2626)}
.ptf-insight-cell.is-positive{--tone:var(--ptf-success, #16a34a)}
.ptf-insight-cell.is-info{--tone:var(--ptf-primary)}
.ptf-insight-cell-label{
  display:inline-flex;
  align-items:center;
  gap:6px;
  color:var(--area-tone, var(--tone));
  font-size:.66rem;
  font-weight:850;
  letter-spacing:.05em;
  text-transform:uppercase;
}
.ptf-insight-icon{
  width:22px;
  height:22px;
  min-width:22px;
  border-radius:8px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  color:var(--area-tone, var(--tone));
  background:color-mix(in srgb, var(--area-tone, var(--tone)) 11%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--area-tone, var(--tone)) 24%, transparent);
}
.ptf-insight-icon svg{
  width:14px;
  height:14px;
  display:block;
}
.ptf-insight-cell-title{
  color:var(--ptf-text);
  font-size:.83rem;
  line-height:1.22;
  font-weight:850;
  overflow:hidden;
  text-overflow:ellipsis;
  display:-webkit-box;
  -webkit-line-clamp:2;
  -webkit-box-orient:vertical;
}
.ptf-insight-cell-message{
  color:var(--ptf-text);
  font-size:.78rem;
  line-height:1.32;
  overflow:hidden;
  text-overflow:ellipsis;
  display:-webkit-box;
  -webkit-line-clamp:3;
  -webkit-box-orient:vertical;
}
.ptf-insight-cell-action{
  color:var(--ptf-muted);
  font-size:.72rem;
  line-height:1.3;
  font-weight:700;
  overflow:hidden;
  text-overflow:ellipsis;
  display:-webkit-box;
  -webkit-line-clamp:2;
  -webkit-box-orient:vertical;
}
.ptf-insight-tag{
  display:inline-flex;
  align-items:center;
  gap:5px;
  align-self:flex-start;
  min-height:21px;
  padding:2px 7px;
  border-radius:999px;
  color:var(--tag-tone);
  background:color-mix(in srgb, var(--tag-tone) 9%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--tag-tone) 24%, transparent);
  font-size:.68rem;
  line-height:1;
  font-weight:850;
  letter-spacing:.03em;
  white-space:nowrap;
}
.ptf-insight-tag.is-ticker{
  color:var(--ptf-text);
}
.ptf-insight-tag-dot{
  width:8px;
  height:8px;
  min-width:8px;
  border-radius:50%;
  display:inline-block;
  background:var(--tag-tone);
  box-shadow:0 0 0 2px color-mix(in srgb, var(--tag-tone) 12%, transparent);
}
@media (max-width: 860px){
  .ptf-insights-head{align-items:flex-start;flex-direction:column}
  .ptf-insights-grid{grid-template-columns:repeat(2, minmax(0,1fr))}
}
@media (max-width: 560px){
  .ptf-insights-grid{grid-template-columns:1fr}
}
[data-testid="stForm"]{
  background:color-mix(in srgb, var(--ptf-surface) 92%, var(--ptf-surface-2));
  border:1px solid var(--ptf-border);
  border-radius:22px;
  padding:18px 18px 10px 18px;
  box-shadow:var(--ptf-shadow);
}
[data-testid="stForm"] [data-testid="stFormSubmitButton"]{
  margin-top:8px;
}
[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button{
  min-height:42px;
  font-size:0.94rem;
  border-radius:14px;
  border:1px solid color-mix(in srgb, var(--ptf-primary) 36%, transparent);
  background:color-mix(in srgb, var(--ptf-primary) 12%, var(--ptf-surface));
  color:var(--ptf-text);
  font-weight:700;
  box-shadow:var(--ptf-shadow);
}
[data-testid="stForm"] [data-testid="stFormSubmitButton"] > button:hover{
  border-color:color-mix(in srgb, var(--ptf-primary) 56%, transparent);
  transform:translateY(-1px);
}
[data-testid="stForm"] h3{
  margin-top:0.5rem!important;
}
[data-testid="stFileUploader"],
[data-testid="stCodeBlock"],
[data-testid="stDownloadButton"]{
  color:var(--ptf-text)!important;
}
[data-testid="stCodeBlock"] pre,
[data-testid="stCode"] pre{
  background:var(--ptf-surface-2)!important;
  color:var(--ptf-text)!important;
  border:1px solid var(--ptf-border)!important;
  border-radius:16px!important;
}
[data-testid="stAlert"]{
  border-radius:16px!important;
  border:1px solid var(--ptf-border)!important;
  box-shadow:var(--ptf-shadow);
}
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p{
  color:var(--ptf-text)!important;
}
hr,.section-divider{border:none;height:1px;background:var(--ptf-border);margin:1.5rem 0;opacity:0.7}
header[data-testid="stHeader"]{background:var(--ptf-bg)!important;backdrop-filter:blur(8px);border-bottom:1px solid var(--ptf-border)}
[data-testid="stToolbar"]{top:0.45rem;right:0.75rem}
[data-testid="stSidebar"]{background:var(--ptf-surface-2)!important; border-right:1px solid var(--ptf-border)}
[data-testid="stSidebar"] [data-testid="stExpander"]{background:var(--ptf-surface)!important}
[data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stCaption{color:var(--ptf-text)!important}
.stButton > button, [data-testid="stBaseButton-secondary"]{
  border-radius:14px;
  border:1px solid color-mix(in srgb, var(--ptf-primary) 36%, transparent);
  background:color-mix(in srgb, var(--ptf-primary) 12%, var(--ptf-surface));
  color:var(--ptf-text);
  font-weight:700;
  box-shadow:var(--ptf-shadow)
}
.stButton > button:hover{border-color:color-mix(in srgb, var(--ptf-primary) 56%, transparent);transform:translateY(-1px)}
.stButton > button:focus,.stButton > button:active,.stButton > button:focus-visible{outline:none!important;box-shadow:0 0 0 3px color-mix(in srgb, var(--ptf-primary) 30%, transparent)!important}
[data-testid="stTabs"] [role="tablist"]{gap:6px;border-bottom:1px solid color-mix(in srgb, var(--ptf-text) 12%, transparent);padding-bottom:4px;flex-wrap:nowrap}
[data-testid="stTabs"] [data-testid="stTab"]{border-radius:14px 14px 0 0;padding:8px 10px;background:color-mix(in srgb, var(--ptf-surface-2) 75%, var(--ptf-surface));color:var(--ptf-text);border:1px solid color-mix(in srgb, var(--ptf-text) 12%, transparent);border-bottom:none;box-shadow:0 4px 14px rgba(0,0,0,0.05);min-width:auto;font-size:0.86rem}
[data-testid="stTabs"] [data-testid="stTab"] *{font-size:0.86rem!important}
.stTabs [aria-selected="true"]{background:color-mix(in srgb, var(--ptf-primary) 18%, var(--ptf-surface));border:1px solid color-mix(in srgb, var(--ptf-primary) 36%, transparent);border-bottom:3px solid var(--ptf-primary)}
div[data-testid="stExpander"]{border:1px solid var(--ptf-border);border-radius:16px;overflow:hidden;box-shadow:var(--ptf-shadow);background:var(--ptf-surface)!important}
div[data-testid="stPlotlyChart"]{
  background:var(--ptf-surface)!important;
  border:1px solid var(--ptf-border);
  border-radius:22px;
  padding:8px 10px 4px 10px;
  box-shadow:var(--ptf-shadow);
  margin-bottom:6px;
  overflow:hidden
}
div[data-testid="stPlotlyChart"] .js-plotly-plot,
div[data-testid="stPlotlyChart"] .plot-container,
div[data-testid="stPlotlyChart"] .svg-container{
  overflow:hidden !important;
}
.quote-history-status{
  display:flex;
  justify-content:flex-end;
  align-items:center;
  flex-wrap:wrap;
  gap:6px 10px;
  margin:-2px 4px 14px 4px;
  color:var(--ptf-muted);
  font-size:0.74rem;
  line-height:1.35;
  text-align:right;
}
.quote-history-status strong{
  color:var(--ptf-text);
  font-weight:800;
}
.quote-history-status__dot{
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--ptf-primary);
  box-shadow:0 0 0 3px color-mix(in srgb, var(--ptf-primary) 12%, transparent);
  flex:none;
}
.quote-history-status.ok .quote-history-status__dot{
  background:#16a34a;
  box-shadow:0 0 0 3px rgba(22,163,74,.12);
}
.quote-history-status.hold .quote-history-status__dot{
  background:#d97706;
  box-shadow:0 0 0 3px rgba(217,119,6,.14);
}
.quote-history-status.warn{
  color:color-mix(in srgb, #dc2626 78%, var(--ptf-muted));
}
.quote-history-status.warn .quote-history-status__dot{
  background:#dc2626;
  box-shadow:0 0 0 3px rgba(220,38,38,.13);
}
.quote-history-status.muted .quote-history-status__dot{
  background:color-mix(in srgb, var(--ptf-muted) 72%, transparent);
  box-shadow:none;
}
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"], div[data-testid="stTable"]{
  border:1px solid var(--ptf-border);
  border-radius:22px;
  padding:6px 0 2px 0;
  box-shadow:var(--ptf-shadow);
  overflow:hidden;
  box-sizing:border-box;
  width:100%
}
[data-testid="stDataEditor"] [role="columnheader"]{
  justify-content:center !important;
  text-align:center !important;
}
[data-testid="stDataEditor"] [role="gridcell"]{
  text-align:center !important;
}
[data-testid="stDataEditor"] [role="gridcell"] > div{
  justify-content:center !important;
  text-align:center !important;
}
[data-testid="stDataEditor"] input{
  text-align:center !important;
}
.table-shell{
  background:var(--ptf-surface);
  border:1px solid var(--ptf-border);
  border-radius:22px;
  padding:8px 10px;
  box-shadow:var(--ptf-shadow);
  overflow:auto;
}
.table-shell table{
  width:100%;
  border-collapse:separate;
  border-spacing:0;
  background:var(--ptf-surface);
  font-size:0.94rem;
}
.table-shell thead th{
  position:sticky;
  top:0;
  background:var(--ptf-surface-2);
  color:var(--ptf-text) !important;
  font-weight:800;
  text-align:left;
  padding:10px 12px;
  border-bottom:1px solid var(--ptf-border);
  z-index:1;
}
.table-shell tbody td{
  background:var(--ptf-surface);
  color:var(--ptf-text) !important;
  padding:9px 12px;
  border-bottom:1px solid color-mix(in srgb, var(--ptf-text) 12%, transparent);
}
.table-shell tbody tr:nth-child(even) td{background:color-mix(in srgb, var(--ptf-surface-2) 70%, var(--ptf-surface));}
.table-shell tbody tr:hover td{background:color-mix(in srgb, var(--ptf-primary) 8%, var(--ptf-surface));}
.sator-area-strip{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 10px 0;justify-content:center}
.sator-area-badge{
  display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;
  font-size:0.76rem;font-weight:800;letter-spacing:.04em;color:var(--tone);background:color-mix(in srgb, var(--tone) 10%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--tone) 22%, transparent)
}
.sator-area-badge.is-context{--tone:var(--ptf-primary)}
.sator-area-badge.is-factor{--tone:var(--ptf-warning)}
.sator-area-badge.is-summary{--tone:var(--ptf-success)}
.sator-area-badge.is-scenario{--tone:var(--ptf-muted)}
.sator-explain{
  display:block!important;
  width:100%;
  box-sizing:border-box;
  margin:8px 0 14px 0;
  padding:10px 14px;
  background:color-mix(in srgb, var(--ptf-primary) 8%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--ptf-primary) 18%, transparent);
  border-left:4px solid var(--ptf-primary);
  border-radius:16px;
  color:var(--ptf-text);
  font-size:0.86rem;
  line-height:1.60;
  box-shadow:var(--ptf-shadow);
}
.sator-explain-title{
  display:block;
  font-weight:850;
  margin:0 0 6px 0;
  color:var(--ptf-text);
}
.sator-explain-row{
  display:grid;
  grid-template-columns:minmax(118px, 150px) minmax(0,1fr);
  gap:14px;
  align-items:start;
  padding:6px 0;
  border-top:1px solid color-mix(in srgb, var(--ptf-text) 10%, transparent);
}
.sator-explain-title + .sator-explain-row,
.sator-explain-row:first-child{
  border-top:0;
  padding-top:0;
}
.sator-explain-key{
  font-weight:850;
  color:var(--ptf-text);
}
.sator-explain-text{
  color:var(--ptf-text);
}
.sator-explain-line{
  padding:2px 0;
}
.sator-explain-line--cols{
  display:grid;
  gap:0 10px;
  align-items:baseline;
}
.sator-explain-line--cols > span:first-child{
  font-weight:700;
}
.sator-explain-line--cols > span:last-child{
  text-align:right;
  white-space:nowrap;
}
.sator-explain-title,
.sator-explain-key,
.sator-explain-text{
  font-size:0.86rem;
  line-height:1.60;
}
.bucket-alloc-card{
  width:100%;box-sizing:border-box;margin:8px 0 14px 0;
  background:var(--ptf-surface);
  border:1px solid var(--ptf-border);
  border-radius:16px;
  box-shadow:var(--ptf-shadow);
  overflow:hidden;
}
.bucket-alloc-table{width:100%;border-collapse:collapse;font-size:0.86rem}
.bucket-alloc-table thead th{
  text-align:left;padding:10px 14px;font-weight:800;font-size:0.72rem;
  letter-spacing:.04em;text-transform:uppercase;color:var(--ptf-muted);
  border-bottom:1px solid var(--ptf-border);
}
.bucket-alloc-table thead th.num{text-align:right}
.bucket-alloc-table td{color:var(--ptf-text)}
.bucket-alloc-table td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.bucket-alloc-bucket-row td{
  padding:12px 14px 8px 14px;
  border-top:1px solid var(--ptf-border);
  background:color-mix(in srgb, var(--tone) 7%, var(--ptf-surface));
}
.bucket-alloc-bucket-row:first-child td{border-top:0}
.bucket-alloc-bucket-name{
  font-weight:850;font-size:0.95rem;color:var(--tone);
  display:inline-flex;align-items:center;gap:8px;
}
.bucket-alloc-bucket-name .dot{width:9px;height:9px;border-radius:50%;background:var(--tone);display:inline-block;flex:none}
.bucket-alloc-bar-track{
  position:relative;height:10px;border-radius:6px;
  background:color-mix(in srgb, var(--ptf-text) 10%, var(--ptf-surface));
}
.bucket-alloc-bar-fill{
  position:absolute;left:0;top:0;bottom:0;border-radius:6px;
  background:var(--tone);
  transition:width .25s ease;
}
.bucket-alloc-bar-target{
  position:absolute;top:-3px;bottom:-3px;width:2px;
  background:var(--ptf-text);opacity:.6;
}
.bucket-alloc-bar-target::before{
  content:"";position:absolute;top:-5px;left:50%;transform:translateX(-50%);
  border-left:4px solid transparent;border-right:4px solid transparent;
  border-top:5px solid var(--ptf-text);opacity:.6;
}
.bucket-alloc-bar-caption{
  display:flex;justify-content:space-between;gap:8px;margin-top:5px;
  font-size:0.74rem;color:var(--ptf-muted);
}
.bucket-alloc-scost{font-weight:800;white-space:nowrap}
.bucket-alloc-scost.ok{color:var(--ptf-success)}
.bucket-alloc-scost.warn{color:var(--ptf-warning)}
.bucket-alloc-scost.bad{color:var(--ptf-danger)}
.bucket-alloc-instrument-row td{
  padding:7px 14px;border-top:1px solid color-mix(in srgb, var(--ptf-border) 55%, transparent);
}
.bucket-alloc-instrument-row:hover td{background:color-mix(in srgb, var(--tone) 6%, transparent)}
.bucket-alloc-ticker{font-weight:700;color:var(--ptf-text)}
.bucket-alloc-natura{display:inline-flex;align-items:center;gap:6px;color:var(--ptf-muted);font-size:0.78rem;padding-left:17px}
.bucket-alloc-natura svg{width:14px;height:14px;color:var(--natura-color);flex:none}
.bucket-alloc-mini-track{position:relative;height:6px;border-radius:4px;background:color-mix(in srgb, var(--ptf-text) 10%, var(--ptf-surface));min-width:70px}
.bucket-alloc-mini-fill{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--tone);opacity:.8}
.bucket-alloc-instrument-row.warn .bucket-alloc-mini-fill{background:var(--ptf-warning)}
.bucket-alloc-instrument-row.bad .bucket-alloc-mini-fill{background:var(--ptf-danger)}
.bucket-alloc-mini-caption{display:block;margin-top:3px;font-size:0.72rem;color:var(--ptf-muted)}
.bucket-alloc-watchlist-row td{
  padding:7px 14px;border-top:1px dashed color-mix(in srgb, var(--ptf-border) 55%, transparent);
  opacity:.55;
}
.bucket-alloc-total-row td{
  padding:10px 14px;border-top:2px solid var(--ptf-border);
  font-weight:850;
}
.ref-snapshot-card{
  width:100%;box-sizing:border-box;margin:8px 0 14px 0;
  background:var(--ptf-surface);
  border:1px solid var(--ptf-border);
  border-radius:16px;
  box-shadow:var(--ptf-shadow);
  overflow:hidden;
}
.ref-snapshot-head{
  display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap;
  padding:12px 14px 10px 14px;
  border-bottom:1px solid var(--ptf-border);
  background:color-mix(in srgb, var(--ptf-primary) 7%, var(--ptf-surface));
}
.ref-snapshot-title{font-weight:850;font-size:0.9rem;color:var(--ptf-text)}
.ref-snapshot-note{font-size:0.78rem;color:var(--ptf-muted)}
.ref-snapshot-body{padding:12px 14px 14px 14px}
.ref-snapshot-amount-row{
  display:flex;justify-content:space-between;align-items:baseline;gap:8px;
  font-size:0.86rem;color:var(--ptf-text);margin-bottom:5px;
}
.ref-snapshot-amount-row .val{font-weight:850}
.ref-snapshot-amount-row .cap{font-size:0.74rem;color:var(--ptf-muted)}
.ref-snapshot-over{font-weight:800;white-space:nowrap;margin-left:6px}
.ref-snapshot-over.ok{color:var(--ptf-success)}
.ref-snapshot-over.bad{color:var(--ptf-danger)}
.ref-snapshot-bar-track{
  --tone:var(--ptf-primary);
  position:relative;height:8px;border-radius:6px;margin-bottom:14px;
  background:color-mix(in srgb, var(--ptf-text) 10%, var(--ptf-surface));
}
.ref-snapshot-bar-fill{
  position:absolute;left:0;top:0;bottom:0;border-radius:6px;
  background:var(--tone);transition:width .25s ease;
}
.ref-snapshot-bar-target{
  position:absolute;top:-3px;bottom:-3px;width:2px;
  background:var(--ptf-text);opacity:.6;
}
.ref-snapshot-bar-target::before{
  content:"";position:absolute;top:-5px;left:50%;transform:translateX(-50%);
  border-left:4px solid transparent;border-right:4px solid transparent;
  border-top:5px solid var(--ptf-text);opacity:.6;
}
.ref-snapshot-judgement{
  display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:0 0 14px 0;
}
.ref-snapshot-judgement div{
  background:color-mix(in srgb, var(--ptf-primary) 5%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--ptf-border) 75%, transparent);
  border-radius:10px;padding:8px 10px;
}
.ref-snapshot-judgement span{
  display:block;font-size:0.68rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;
  color:var(--ptf-muted);margin-bottom:2px;
}
.ref-snapshot-judgement b{font-size:0.9rem;color:var(--ptf-text)}
.ref-snapshot-judgement b.ok{color:var(--ptf-success)}
.ref-snapshot-judgement b.warn{color:var(--ptf-warning)}
.ref-snapshot-judgement b.bad{color:var(--ptf-danger)}
.ref-snapshot-exec{
  display:grid;
  grid-template-columns:minmax(150px,1.2fr) repeat(6,minmax(86px,1fr));
  gap:8px;
  margin:0 0 14px 0;
  padding:10px 0;
  border-top:1px solid color-mix(in srgb, var(--ptf-border) 70%, transparent);
  border-bottom:1px solid color-mix(in srgb, var(--ptf-border) 70%, transparent);
}
.ref-snapshot-exec-title,
.ref-snapshot-exec div{
  min-width:0;
}
.ref-snapshot-exec span{
  display:block;
  font-size:0.66rem;
  font-weight:800;
  letter-spacing:.04em;
  text-transform:uppercase;
  color:var(--ptf-muted);
  margin-bottom:2px;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.ref-snapshot-exec b{
  display:block;
  font-size:0.82rem;
  line-height:1.15;
  color:var(--ptf-text);
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  font-variant-numeric:tabular-nums;
}
.ref-snapshot-exec b.ok{color:var(--ptf-success)}
.ref-snapshot-exec b.warn{color:var(--ptf-warning)}
.ref-snapshot-exec b.bad{color:var(--ptf-danger)}
.ref-snapshot-exec b span{
  display:inline;
  font-size:0.72rem;
  font-weight:800;
  color:var(--ptf-muted);
  text-transform:none;
  letter-spacing:0;
  margin:0 0 0 4px;
}
@media (max-width: 980px){
  .ref-snapshot-exec{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media (max-width: 640px){
  .ref-snapshot-exec{grid-template-columns:repeat(2,minmax(0,1fr))}
}
.ref-snapshot-mix{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}
.ref-snapshot-mix-row{display:grid;grid-template-columns:90px 1fr 46px;align-items:center;gap:8px}
.ref-snapshot-mix-label{
  font-size:0.78rem;font-weight:700;color:var(--tone);
  display:inline-flex;align-items:center;gap:6px;
}
.ref-snapshot-mix-label .dot{width:8px;height:8px;border-radius:50%;background:var(--tone);display:inline-block;flex:none}
.ref-snapshot-mix-track{position:relative;height:6px;border-radius:4px;background:color-mix(in srgb, var(--ptf-text) 10%, var(--ptf-surface))}
.ref-snapshot-mix-fill{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--tone);opacity:.85}
.ref-snapshot-mix-pct{font-size:0.78rem;text-align:right;color:var(--ptf-muted);font-variant-numeric:tabular-nums}
.ref-snapshot-lines-label{font-size:0.72rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--ptf-muted);margin-bottom:6px}
.ref-snapshot-alerts{margin:0 0 14px 0}
.ref-snapshot-alert{
  display:grid;grid-template-columns:minmax(120px,.36fr) 1fr;gap:8px;align-items:start;
  background:color-mix(in srgb, var(--ptf-warning) 7%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--ptf-warning) 22%, var(--ptf-border));
  border-radius:10px;padding:7px 9px;margin-bottom:6px;
}
.ref-snapshot-alert b{font-size:0.78rem;color:var(--ptf-text)}
.ref-snapshot-alert span{font-size:0.76rem;color:var(--ptf-muted);line-height:1.25}
.ref-snapshot-lines{width:100%;overflow-x:auto}
.ref-snapshot-lines table{width:100%;border-collapse:collapse;font-size:0.84rem}
.ref-snapshot-lines thead th{
  text-align:left;padding:4px 8px 6px 8px;font-weight:800;font-size:0.66rem;
  letter-spacing:.04em;text-transform:uppercase;color:var(--ptf-muted);
  border-bottom:1px solid var(--ptf-border);
}
.ref-snapshot-lines thead th.num{text-align:right}
.ref-snapshot-lines td{padding:4px 8px;border-top:1px solid color-mix(in srgb, var(--ptf-border) 55%, transparent);vertical-align:middle}
.ref-snapshot-lines tr:first-child td{border-top:0}
.ref-snapshot-lines td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--ptf-muted)}
.ref-snapshot-bucket-dot{width:7px;height:7px;border-radius:50%;background:var(--tone);display:inline-block;flex:none}
.ref-snapshot-natura{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;flex:none}
.ref-snapshot-natura svg{width:14px;height:14px;color:var(--natura-color)}
.ref-snapshot-instrument{display:flex;align-items:center;gap:7px;min-width:0}
.ref-snapshot-instrument-text{display:flex;align-items:baseline;gap:6px;min-width:0;white-space:nowrap;overflow:hidden}
.ref-snapshot-instrument-text .ticker{font-weight:700;color:var(--ptf-text);flex:none}
.ref-snapshot-instrument-text .name{
  font-size:0.74rem;color:var(--ptf-muted);overflow:hidden;text-overflow:ellipsis;
}
.ref-snapshot-footnote{font-size:0.72rem;color:var(--ptf-muted);margin-top:8px;font-style:italic}
[data-testid="stMetric"]{
  background:var(--ptf-surface);
  border:1px solid var(--ptf-border);
  border-radius:18px;
  padding:10px 12px;
  box-shadow:var(--ptf-shadow);
}
[data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"]{
  color:var(--ptf-text)!important;
}
.header-panel{
  border-radius:20px;
  box-shadow:var(--ptf-shadow);
  margin:0 0 1.15rem 0;
  display:flex;
  flex-wrap:wrap;
  overflow:hidden;
  border:1px solid var(--ptf-border);
}
.header-main{flex:1 1 320px;background:var(--ptf-surface);padding:22px 26px;min-width:0}
.header-top{display:flex;align-items:center;gap:12px;margin-bottom:6px}
.header-icon{
  width:42px;height:42px;border-radius:12px;flex:0 0 auto;
  background:linear-gradient(135deg, var(--ptf-primary), color-mix(in srgb, var(--ptf-primary) 55%, #7c4dff));
  display:flex;align-items:center;justify-content:center;font-size:20px;
  box-shadow:0 3px 8px color-mix(in srgb, var(--ptf-primary) 40%, transparent);
}
.header-title{font-size:1.85rem;font-weight:800;color:var(--ptf-text);line-height:1.05}
.header-sub{font-size:0.92rem;color:var(--ptf-muted);line-height:1.5}
.header-side{
  flex:0 0 168px;
  padding:16px 18px;
  display:flex;flex-direction:column;gap:10px;justify-content:center;
  background:linear-gradient(160deg, color-mix(in srgb, var(--ptf-primary) 28%, #0b0f1a), color-mix(in srgb, var(--ptf-primary) 42%, #0b0f1a));
  color:#fff;
}
.header-side-row{display:flex;align-items:center;justify-content:space-between;gap:10px}
.header-side-label{font-size:0.68rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;opacity:.55;white-space:nowrap}
.header-side-val{font-size:0.85rem;font-weight:700;display:flex;align-items:center;gap:6px;white-space:nowrap}
.header-side-val.accent{color:color-mix(in srgb, var(--ptf-primary) 55%, #fff)}
.header-side-div{height:1px;background:rgba(255,255,255,.14)}
.shutdown-shell{
  min-height:52vh;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:48px 16px;
}
.shutdown-panel{
  width:min(720px,100%);
  display:flex;
  align-items:flex-start;
  gap:18px;
  padding:28px;
  border:1px solid var(--ptf-border);
  border-radius:18px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--ptf-primary) 7%, var(--ptf-surface)), var(--ptf-surface) 62%),
    var(--ptf-surface);
  box-shadow:var(--ptf-shadow);
  position:relative;
  overflow:hidden;
}
.shutdown-panel:before{
  content:"";
  position:absolute;
  inset:0 0 auto 0;
  height:3px;
  background:linear-gradient(90deg, var(--ptf-primary), color-mix(in srgb, var(--ptf-primary) 36%, #10B981));
}
.shutdown-mark{
  width:48px;
  height:48px;
  border-radius:14px;
  display:flex;
  align-items:center;
  justify-content:center;
  flex:none;
  background:var(--ptf-text);
  color:var(--ptf-surface);
  font-size:1.25rem;
  font-weight:900;
}
.shutdown-content{min-width:0}
.shutdown-kicker{
  font-size:0.72rem;
  line-height:1.2;
  font-weight:900;
  letter-spacing:0;
  color:var(--ptf-muted);
}
.shutdown-title{
  margin-top:4px;
  font-size:1.7rem;
  line-height:1.08;
  font-weight:900;
  color:var(--ptf-text);
}
.shutdown-sub{
  margin-top:10px;
  max-width:560px;
  font-size:0.96rem;
  line-height:1.45;
  color:var(--ptf-muted);
}
.shutdown-footer{
  margin-top:18px;
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:10px;
}
.shutdown-pill{
  display:inline-flex;
  align-items:center;
  padding:7px 10px;
  border-radius:999px;
  background:color-mix(in srgb, var(--ptf-primary) 12%, var(--ptf-surface));
  color:var(--ptf-primary);
  font-size:0.78rem;
  font-weight:850;
}
.shutdown-command{
  font-size:0.78rem;
  color:var(--ptf-muted);
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
.header-executive{
  display:grid;
  grid-template-columns:minmax(340px,1fr) minmax(330px,auto);
  align-items:center;
  gap:18px;
  padding:14px 18px;
  border:1px solid color-mix(in srgb, var(--ptf-primary) 9%, var(--ptf-border));
  border-radius:22px;
  box-shadow:0 10px 28px rgba(15,23,42,.07);
  background:
    linear-gradient(135deg,
      color-mix(in srgb, var(--ptf-primary) 8%, var(--ptf-surface)),
      color-mix(in srgb, #10B981 5%, var(--ptf-surface)) 58%,
      var(--ptf-surface)
    );
  overflow:hidden;
  position:relative;
}
.header-brand{display:flex;align-items:center;gap:14px;min-width:0}
.header-brand-logo-wrap{
  min-height:98px;
  align-self:stretch;
  justify-content:flex-start;
  padding:0;
  border:0;
  border-radius:0;
  background:transparent;
  box-shadow:none;
}
.header-brand-logo{
  display:block;
  width:auto;
  height:clamp(82px, 6.8vw, 110px);
  max-width:min(100%, 620px);
  object-fit:contain;
  object-position:left center;
  border:0;
}
.header-brand-mark{
  width:44px;
  height:44px;
  border-radius:12px;
  display:flex;
  align-items:center;
  justify-content:center;
  flex:none;
  background:var(--ptf-text);
  color:var(--ptf-surface);
  font-size:1.25rem;
  font-weight:900;
  box-shadow:0 8px 18px rgba(0,0,0,.12);
}
.header-brand-copy{min-width:0}
.header-tagline{
  font-size:0.82rem;
  line-height:1.2;
  font-weight:800;
  letter-spacing:0;
  color:var(--ptf-muted);
  margin-top:5px;
}
.header-executive .header-title{
  font-size:1.74rem;
  line-height:1;
  font-weight:900;
}
.header-executive .header-sub{
  font-size:0.9rem;
  line-height:1.35;
  margin-top:4px;
}
.header-right{
  display:flex;
  flex-direction:column;
  gap:7px;
  min-width:0;
  align-self:stretch;
  justify-content:center;
}
.header-meta{
  display:grid;
  grid-template-columns:repeat(3,minmax(96px,1fr));
  gap:6px;
  align-items:stretch;
}
.header-chip{
  min-width:0;
  min-height:44px;
  padding:7px 9px;
  border-radius:10px;
  border:1px solid color-mix(in srgb, var(--ptf-border) 76%, #fff);
  background:rgba(255,255,255,.62);
  display:flex;
  flex-direction:column;
  justify-content:center;
  gap:3px;
  text-align:center;
}
.header-chip-label{
  font-size:0.60rem;
  font-weight:800;
  letter-spacing:0;
  text-transform:uppercase;
  color:var(--ptf-muted);
  white-space:nowrap;
}
.header-chip-value{
  font-size:0.78rem;
  font-weight:800;
  line-height:1.2;
  color:var(--ptf-text);
  display:flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  white-space:nowrap;
}
.header-chip-value.accent{color:var(--ptf-primary)}
.header-status-dot{
  width:8px;
  height:8px;
  border-radius:50%;
  background:var(--status-color);
  box-shadow:0 0 0 3px color-mix(in srgb, var(--status-color) 18%, transparent);
  flex:none;
}
.header-timeline{
  display:flex;
  justify-content:flex-end;
  gap:6px;
  flex-wrap:wrap;
  font-size:0.70rem;
  line-height:1.25;
  color:var(--ptf-muted);
}
.header-timeline span{
  display:inline-flex;
  align-items:baseline;
  gap:5px;
  white-space:nowrap;
  padding:5px 8px;
  border:1px solid color-mix(in srgb, var(--ptf-border) 72%, #fff);
  border-radius:999px;
  background:rgba(255,255,255,.50);
}
.header-timeline strong{
  color:var(--ptf-text);
  font-weight:850;
}
@media (max-width: 920px){
  .header-executive{grid-template-columns:1fr;padding:13px 14px;gap:10px}
  .header-right{width:100%}
  .header-meta{grid-template-columns:repeat(3,minmax(0,1fr))}
  .header-chip{padding:7px 8px}
  .header-executive .header-title{font-size:1.42rem}
  .header-timeline{justify-content:flex-start}
  .header-brand-logo-wrap{min-height:78px;padding:0}
  .header-brand-logo{height:clamp(72px, 13vw, 92px);max-width:100%}
}
@media (max-width: 560px){
  .header-meta{grid-template-columns:1fr}
  .header-brand-mark{width:40px;height:40px}
  .header-brand-logo-wrap{min-height:66px;padding:0}
  .header-brand-logo{height:auto;width:100%;max-height:80px}
  .header-timeline span{width:100%;justify-content:space-between}
}
.stMarkdown h3{margin-top:1rem;margin-bottom:0.5rem;padding:0;color:var(--ptf-text)}
.kpi-card{background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 6%, var(--ptf-surface)), var(--ptf-surface));border:1px solid var(--ptf-border);border-radius:22px;padding:12px 14px 10px 14px;box-shadow:0 4px 12px rgba(0,0,0,0.08);position:relative;overflow:hidden;min-height:124px;height:100%;display:flex;flex-direction:column;justify-content:flex-start;align-items:center;text-align:center;transition:box-shadow 0.18s ease, transform 0.15s ease;cursor:default}
.kpi-card:hover{box-shadow:0 6px 20px rgba(91,141,239,0.18);transform:translateY(-1px)}
.kpi-card:before{content:"";position:absolute;left:0;top:0;width:100%;height:4px;background:var(--accent)}
.kpi-label{font-size:0.72rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ptf-muted);margin-bottom:6px;text-align:center;width:100%}
.kpi-value{font-size:1.28rem;font-weight:800;color:var(--ptf-text);line-height:1.12;margin-bottom:6px;word-break:break-word;text-align:center;width:100%}
.kpi-sub{font-size:0.78rem;color:var(--ptf-muted);line-height:1.25;margin-top:auto;text-align:center;width:100%}
.kpi-triplet{display:grid;grid-template-columns:repeat(var(--kpi-triplet-cols,3),minmax(0,1fr));gap:8px;margin-top:0;margin-bottom:4px;width:100%}
.kpi-triplet-cell{display:flex;flex-direction:column;gap:2px;padding:6px 8px;border:1px solid var(--ptf-border);border-radius:14px;background:color-mix(in srgb, var(--ptf-primary) 4%, var(--ptf-surface));min-width:0}
.kpi-triplet-tag{font-weight:800;color:var(--ptf-muted);letter-spacing:.04em;text-align:left}
.kpi-triplet-tag-gov{color:#E8B960}
.kpi-triplet-tag-azi{color:#EF6C9A}
.kpi-triplet-tag-etf{color:#5B8DEF}
.kpi-triplet-tag-fnd{color:#B07CC6}
.kpi-triplet-tag-obb{color:#7E57C2}
.kpi-triplet-tag-etc{color:#C2410C}
.kpi-triplet-tag-liq{color:#26A69A}
.kpi-triplet-tag-der{color:#8E44AD}
.kpi-triplet-tag-altro{color:#6EC6C6}
.kpi-triplet-value{font-weight:800;color:var(--ptf-text);font-size:0.88rem;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.kpi-triplet-pl{font-size:0.72rem;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.kpi-triplet-pl.is-neg{color:#c0392b}
.kpi-triplet-pl.is-pos{color:#1E8449}
.kpi-triplet-pl.is-neutral{color:var(--ptf-muted)}
.metric-guide{display:flex;flex-direction:column;gap:8px;width:100%}
.metric-guide-2col{display:grid;grid-template-columns:1fr 1fr;gap:4px 28px;width:100%}
.metric-guide-line{display:flex;align-items:flex-start;gap:10px;width:100%;color:var(--ptf-text)}
.metric-guide-key{flex:0 0 76px;font-weight:800;color:var(--ptf-text)}
.metric-guide-desc{flex:1 1 auto;color:var(--ptf-text)}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.kpi-card){flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.kpi-card) > div{flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.kpi-card) .stMarkdown{flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.kpi-card) .kpi-card{flex:1 !important}
.pl-mini-title{
  font-size:0.78rem;
  text-transform:uppercase;
  letter-spacing:.08em;
  color:var(--ptf-muted);
  font-weight:700;
  text-align:center;
  margin:8px 0 6px 0
}
.leg{
  background:color-mix(in srgb, var(--ptf-primary) 8%, var(--ptf-surface));
  border:1px solid color-mix(in srgb, var(--ptf-primary) 18%, transparent);
  border-left:4px solid var(--ptf-primary);
  border-radius:16px;
  padding:12px 14px;
  font-size:0.86rem;
  color:var(--ptf-text);
  line-height:1.60;
  box-shadow:var(--ptf-shadow);
  width:100%;
  box-sizing:border-box
}
.leg b{color:var(--ptf-text)}
.leg-top{display:flex;align-items:flex-start;margin:6px 0 12px 0;width:100%;box-sizing:border-box}
.leg-bottom{display:flex;align-items:flex-start;margin:10px 0 16px 0;width:100%;box-sizing:border-box}
.read-table{flex-direction:column;padding:6px 8px}
.read-table table{width:100%;border-collapse:collapse}
.read-table tr{border-bottom:1px solid color-mix(in srgb, var(--ptf-text) 9%, transparent)}
.read-table tr:last-child{border-bottom:none}
.read-table th,.read-table td{padding:8px 10px;text-align:left;vertical-align:top;font-size:0.86rem;line-height:1.5}
.read-table th{font-weight:800;white-space:nowrap;width:1%;color:var(--ptf-text)}
.read-table td.val{font-weight:800;white-space:nowrap;text-align:right;width:1%}
.read-table td.note{color:color-mix(in srgb, var(--ptf-text) 82%, transparent)}
.exit-link{
  display:block;
  text-align:center;
  text-decoration:none;
  padding:10px 14px;
  margin-top:10px;
  border-radius:14px;
  border:1px solid rgba(239,75,75,0.22);
  background:linear-gradient(180deg, rgba(255,75,75,0.10), rgba(255,75,75,0.04));
  color:#9f2f39 !important;
  font-weight:700;
  box-shadow:var(--ptf-shadow)
}
.back-top-link{display:inline-flex;align-items:center;gap:6px;text-decoration:none;padding:8px 12px;border-radius:12px;border:1px solid color-mix(in srgb, var(--ptf-primary) 20%, transparent);background:var(--ptf-surface);color:var(--ptf-primary) !important;font-weight:700;box-shadow:var(--ptf-shadow)}
.back-top-link:hover{border-color:color-mix(in srgb, var(--ptf-primary) 40%, transparent);background:color-mix(in srgb, var(--ptf-primary) 5%, var(--ptf-surface))}
hr{border-color:color-mix(in srgb, var(--ptf-text) 12%, transparent)}
[data-testid="stHorizontalBlock"]{align-items:stretch !important}
[data-testid="stHorizontalBlock"] > div{display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.leg-top){flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.leg-top) > div{flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.leg-top) div[data-testid*="arkdown"]{flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.leg-top) .stMarkdown{flex:1 !important;display:flex !important;flex-direction:column !important}
[data-testid="stHorizontalBlock"] > div > [data-testid="element-container"]:has(.leg-top) .leg-top{flex:1 !important}
[data-testid="stSelectbox"] label,
[data-testid="stNumberInput"] label,
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stCheckbox"] label,
[data-testid="stRadio"] label{
  color:var(--ptf-text)!important;
  font-weight:700!important;
}
[data-testid="stSelectbox"] > div,
[data-testid="stNumberInput"] > div,
[data-testid="stTextInput"] > div,
[data-testid="stTextArea"] textarea{
  color:var(--ptf-text)!important;
}
[data-testid="stSelectbox"] [role="group"],
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea{
  background:var(--ptf-surface)!important;
  border:1px solid var(--ptf-border)!important;
  border-radius:14px!important;
}
[data-testid="stTabs"] [role="tabpanel"]{
  padding-top:8px;
}
</style>"""
    style_css = style_css.replace("__PTF_BG__", theme.bg_app)
    style_css = style_css.replace("__PTF_SURFACE__", theme.bg_surface)
    style_css = style_css.replace("__PTF_SURFACE_ALT__", surface_alt)
    style_css = style_css.replace("__PTF_TEXT__", theme.font_color)
    style_css = style_css.replace("__PTF_MUTED__", theme.muted_color)
    style_css = style_css.replace("__PTF_BORDER__", theme.border_color)
    style_css = style_css.replace("__PTF_PRIMARY__", theme.primary_color)
    style_css = style_css.replace("__PTF_SHADOW__", theme.shadow_color)
    style_css = style_css.replace(".kpi-triplet-tag-gov{color:#E8B960}", f".kpi-triplet-tag-gov{{color:{theme.colors['category_gov']}}}")
    style_css = style_css.replace(".kpi-triplet-tag-etf{color:#5B8DEF}", f".kpi-triplet-tag-etf{{color:{theme.colors['category_etf']}}}")
    style_css = style_css.replace(".kpi-triplet-tag-fnd{color:#B07CC6}", f".kpi-triplet-tag-fnd{{color:{theme.colors['category_fnd']}}}")
    style_css = style_css.replace(".kpi-triplet-tag-etc{color:#C2410C}", f".kpi-triplet-tag-etc{{color:{theme.colors['category_etc']}}}")
    style_css = style_css.replace(".kpi-triplet-pl.is-neg{color:#c0392b}", f".kpi-triplet-pl.is-neg{{color:{theme.colors['danger']}}}")
    style_css = style_css.replace(".kpi-triplet-pl.is-pos{color:#1E8449}", f".kpi-triplet-pl.is-pos{{color:{theme.colors['success']}}}")
    st.markdown(style_css, unsafe_allow_html=True)


def inject_layout_js():
    """Inietta il JS che equalizza le altezze dei box .leg-top e .kpi-card affiancati."""
    render_html_iframe(r"""<script>
(function(){
    var d;
    try{ d=window.parent.document; }catch(e){ return; }

    function eqSelector(selector){
        try{
            var blocks=d.querySelectorAll('[data-testid="stHorizontalBlock"]');
            blocks.forEach(function(b){
                var items=b.querySelectorAll(selector);
                if(items.length<2) return;
                items.forEach(function(l){ l.style.height='auto'; });
                var maxH=0;
                items.forEach(function(l){
                    var h=l.getBoundingClientRect().height;
                    if(h>maxH) maxH=h;
                });
                if(maxH>0) items.forEach(function(l){ l.style.height=maxH+'px'; });
            });
        }catch(e){}
    }
    function runAll(){
        eqSelector('.leg-top');
        eqSelector('.leg-bottom');
        eqSelector('.kpi-card');
    }
    runAll();
    setTimeout(runAll, 200);
    setTimeout(runAll, 1000);
    try{
        var obs = new MutationObserver(function(){ setTimeout(runAll, 80); });
        obs.observe(d.body, {childList:true, subtree:true});
    }catch(e){}
})();
</script>""", height=1, scrolling=False)


# ============================================================================
# COLOR HELPERS - Centralizzazione colori dai temi
# ============================================================================

def get_common_colors(theme=None):
    """
    Ritorna dizionario di colori comuni per grafici.
    
    Se theme non fornito, usa tema default da get_theme_context().
    
    Returns:
        Dict con chiavi: primary, secondary, positive, negative, neutral,
                         muted, background, grid, text, border
    
    Uso in charts.py:
        from ui.styles import get_common_colors
        colors = get_common_colors(theme)
        line=dict(color=colors['primary'], width=2)
    """
    if theme is None:
        theme = get_theme_context()
    
    return {
        'primary': theme.color_blue,        # Linee principali
        'secondary': theme.color_orange,    # Linee secondarie
        'positive': theme.color_green,      # Positivo (P/L, gains)
        'negative': theme.color_red,        # Negativo (drawdown, losses)
        'neutral': theme.color_gray,        # Neutro (cost basis, ecc)
        'muted': getattr(theme, 'color_muted', theme.color_gray),  # Muted text
        'background': theme.bg_chart,       # Sfondo grafico
        'grid': theme.grid_color,           # Grid lines
        'text': theme.font_color,           # Testo assi
        'border': getattr(theme, 'border_color', theme.color_gray),  # Bordi
    }
