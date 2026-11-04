"""
ui/page_chrome.py — Shared page intro and section separators.

Centralizes page-level chrome so title/icon/comment styling is consistent
across the mature 5.0 surfaces.
"""
from __future__ import annotations

import streamlit as st

from ui.theme import get_theme_context


def page_icon_svg(kind: str = "default") -> str:
    icons = {
        "summary": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-summary" x1="3" y1="3" x2="21" y2="21"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="3" width="17" height="18" rx="4" fill="url(#g-summary)" opacity=".16"/>
          <path d="M8 8.2h8M8 12h8M8 15.8h5" fill="none" stroke="url(#g-summary)" stroke-width="1.9" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-summary)"/>
        </svg>
        """,
        "confronto": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-confronto" x1="4" y1="20" x2="20" y2="4"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3" y="4" width="18" height="16" rx="4" fill="url(#g-confronto)" opacity=".14"/>
          <path d="M7 16.5V11M12 16.5V7.5M17 16.5v-4" fill="none" stroke="url(#g-confronto)" stroke-width="2.1" stroke-linecap="round"/>
          <path d="M6.5 17.5h11" stroke="url(#g-confronto)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
        "pianificazione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-plan" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="5" width="17" height="15.5" rx="4" fill="url(#g-plan)" opacity=".15"/>
          <path d="M8 3.5v3M16 3.5v3M6.5 9h11" stroke="url(#g-plan)" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M8 13h3l1.5 2.2L16.5 11" fill="none" stroke="url(#g-plan)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        """,
        "gestione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-data" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="3.5" width="16" height="17" rx="4" fill="url(#g-data)" opacity=".15"/>
          <path d="M8 8h8M8 12h8M8 16h5" stroke="url(#g-data)" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-data)"/>
        </svg>
        """,
        "impostazioni": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-settings" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <circle cx="12" cy="12" r="8.5" fill="url(#g-settings)" opacity=".15"/>
          <path d="M12 8.1v-2M12 18v-2M8.1 12h-2M18 12h-2M9.25 9.25 7.8 7.8M16.2 16.2l-1.45-1.45M14.75 9.25 16.2 7.8M7.8 16.2l1.45-1.45" stroke="url(#g-settings)" stroke-width="1.7" stroke-linecap="round"/>
          <circle cx="12" cy="12" r="3.1" fill="none" stroke="url(#g-settings)" stroke-width="2"/>
        </svg>
        """,
        "portfolio": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-portfolio" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="5" width="17" height="14.5" rx="4" fill="url(#g-portfolio)" opacity=".15"/>
          <path d="M7.5 9.2h9M7.5 12.5h9M7.5 15.8h5.5" fill="none" stroke="url(#g-portfolio)" stroke-width="1.9" stroke-linecap="round"/>
          <circle cx="17.4" cy="15.8" r="1.8" fill="url(#g-portfolio)"/>
        </svg>
        """,
        "analysis": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-analysis" x1="4" y1="20" x2="20" y2="4"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="4" width="17" height="16" rx="4" fill="url(#g-analysis)" opacity=".14"/>
          <path d="M7 16.5V12M11.7 16.5V8.4M16.4 16.5v-5.2" fill="none" stroke="url(#g-analysis)" stroke-width="2.1" stroke-linecap="round"/>
          <path d="M6.5 17.5h11" stroke="url(#g-analysis)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
        "operations": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-operations" x1="5" y1="4" x2="19" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="5" width="16" height="14" rx="4" fill="url(#g-operations)" opacity=".14"/>
          <path d="M8 9.2h8M8 13h5.2M15.8 12.9l1.1 1.1 2.1-2.4" fill="none" stroke="url(#g-operations)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        """,
        "default": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-default" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="4" width="16" height="16" rx="4" fill="url(#g-default)" opacity=".15"/>
          <path d="M8 9h8M8 13h8M8 17h5" stroke="url(#g-default)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
    }
    return icons.get(kind, icons["default"])


def render_page_intro(title: str, comment: str, icon: str = "default", theme=None) -> None:
    theme = theme or get_theme_context()
    accent = getattr(theme, "color_blue", "#3b82f6")
    accent_2 = getattr(theme, "color_green", "#22c55e")
    font = getattr(theme, "font_color", "#111827")
    panel_bg = getattr(theme, "panel_bg", "#f8fafc")
    border = getattr(theme, "border_color", "rgba(148,163,184,.32)")
    st.markdown(
        f"""
        <style>
        .page-intro {{
            --page-accent:{accent};
            --page-accent-2:{accent_2};
            margin:0;
            padding:0;
        }}
        .page-intro-title {{
            display:flex;
            align-items:center;
            gap:10px;
            margin:0 0 8px 0;
            color:{font};
            font-size:1.28rem;
            font-weight:850;
            line-height:1.18;
            letter-spacing:-0.01em;
        }}
        .page-intro-icon {{
            width:27px;
            height:27px;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            flex:0 0 27px;
        }}
        .page-intro-icon svg {{
            width:27px;
            height:27px;
            display:block;
        }}
        .page-intro-comment {{
            margin:0;
            padding:10px 14px;
            color:{font};
            background:{panel_bg};
            border:1px solid {border};
            border-left:4px solid {accent};
            border-radius:14px;
            font-size:0.92rem;
            line-height:1.42;
            font-weight:500;
            box-shadow:0 8px 18px rgba(15,23,42,.04);
        }}
        .section-line {{
            margin:14px 0 14px 0;
            border:0;
            border-top:1px solid rgba(148,163,184,.30);
        }}
        .page-intro + .section-line {{
            margin-top:28px !important;
            margin-bottom:14px !important;
        }}
        </style>
        <div class="page-intro">
          <div class="page-intro-title">
            <span class="page-intro-icon">{page_icon_svg(icon)}</span>
            <span>{title}</span>
          </div>
          <div class="page-intro-comment">{comment}</div>
        </div>
        <hr class="section-line" />
        """,
        unsafe_allow_html=True,
    )


def render_section_line() -> None:
    st.markdown('<hr class="section-line" />', unsafe_allow_html=True)
