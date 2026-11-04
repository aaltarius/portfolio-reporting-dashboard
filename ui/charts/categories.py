from __future__ import annotations

from typing import Any


def normalise_bar_text(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> None:
    """Uniforma testo e clipping delle barre dai parametri di setting."""
    try:
        cliponaxis = bool(settings.get("bar_cliponaxis", global_style.get("bar_cliponaxis", False)))
        default_pos = settings.get("bar_textposition", global_style.get("bar_textposition"))
        default_size = settings.get("bar_textfont_size", global_style.get("bar_textfont_size"))
        h_pos = settings.get("horizontal_bar_textposition", global_style.get("horizontal_bar_textposition", default_pos))
        h_size = settings.get("horizontal_bar_textfont_size", global_style.get("horizontal_bar_textfont_size", default_size))

        for tr in fig.data:
            if getattr(tr, "type", None) != "bar":
                continue

            is_horizontal = getattr(tr, "orientation", None) == "h"
            textposition = h_pos if is_horizontal else default_pos
            text_size = h_size if is_horizontal else default_size

            update: dict[str, Any] = {"cliponaxis": cliponaxis}
            if textposition is not None:
                update["textposition"] = textposition

            if text_size is not None:
                old_font = getattr(tr, "textfont", None)
                font_dict: dict[str, Any] = {}
                try:
                    if old_font:
                        font_dict = old_font.to_plotly_json()
                except Exception:
                    font_dict = {}
                font_dict["size"] = int(text_size)
                update["textfont"] = font_dict

            tr.update(**update)
    except Exception:
        pass


def has_horizontal_bar(fig) -> bool:
    try:
        for tr in fig.data:
            if getattr(tr, "type", None) == "bar" and getattr(tr, "orientation", None) == "h":
                return True
    except Exception:
        pass
    return False


def force_all_y_categories(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> None:
    enabled = bool(settings.get("show_all_y_categories", global_style.get("show_all_y_categories_default", False)))
    if not enabled:
        return
    labels = []
    seen = set()
    for tr in fig.data:
        if getattr(tr, "type", None) != "bar" or getattr(tr, "orientation", None) != "h":
            continue
        y = getattr(tr, "y", None)
        if y is None:
            continue
        for item in list(y):
            key = str(item)
            if key not in seen:
                seen.add(key)
                labels.append(item)
    if not labels:
        return
    try:
        fig.update_yaxes(
            tickmode="array",
            tickvals=labels,
            ticktext=[str(v) for v in labels],
            categoryorder="array",
            categoryarray=labels,
            automargin=True,
        )
    except Exception:
        pass


def force_all_x_categories(fig, settings: dict[str, Any], global_style: dict[str, Any]) -> None:
    enabled = bool(settings.get("show_all_x_categories", False))
    if not enabled:
        return
    labels = []
    seen = set()
    for tr in fig.data:
        if getattr(tr, "type", None) not in {"bar", "waterfall"}:
            continue
        x = getattr(tr, "x", None)
        if x is None:
            continue
        for item in list(x):
            key = str(item)
            if key not in seen:
                seen.add(key)
                labels.append(item)
    if not labels:
        return
    try:
        fig.update_xaxes(
            tickmode="array",
            tickvals=labels,
            ticktext=[str(v) for v in labels],
            categoryorder="array",
            categoryarray=labels,
            tickangle=settings.get("x_tickangle", global_style.get("xaxis_tickangle")),
            automargin=True,
        )
    except Exception:
        pass


def force_heatmap_labels_and_square(fig, settings: dict[str, Any]) -> None:
    if settings.get("type") != "heatmap":
        return

    if bool(settings.get("square", False)):
        try:
            # Se il builder ha gia' impostato un'altezza sulla figura (es.
            # dimensione dinamica in base al numero di righe/colonne, vedi
            # ui/charts/analisi.py::build_correlation_heatmap), quella va
            # rispettata: prima settings.get("height") vinceva sempre
            # perche' e' truthy, azzerando qualunque calcolo dinamico del
            # builder (bug reale, 2026-08-20). settings.py resta il default
            # per i builder che non impostano nulla di proprio.
            h = int(getattr(fig.layout, "height", None) or settings.get("height") or 500)
            w = h  # 'square' impone lato uguale: mai una larghezza statica
                   # disallineata dall'altezza dinamica appena calcolata.
            fig.update_layout(width=w, height=h, autosize=False)
            # constraintoward="top": i margini sinistro+destro (spazio per le
            # etichette y) e alto+basso (spazio per le etichette x ruotate)
            # non sono mai uguali, quindi l'area di plot prima del vincolo
            # quadrato non e' mai quadrata. scaleanchor/scaleratio=1
            # restringe la dimensione piu' grande (di norma l'altezza) per
            # renderla quadrata: senza constraintoward lo spazio residuo si
            # divide sopra E sotto la matrice (default "middle"), lasciando
            # una fascia bianca ben visibile sopra (bug reale, 2026-08-20).
            # "top" ancora la matrice in alto e spinge tutto il residuo in
            # basso, dove le etichette ruotate occupano gia' margine.
            fig.update_yaxes(scaleanchor="x", scaleratio=1, constrain="domain", constraintoward="top")
            fig.update_xaxes(constrain="domain")
        except Exception:
            pass

    if not bool(settings.get("show_all_heatmap_labels", False)):
        return
    try:
        for tr in fig.data:
            if getattr(tr, "type", None) != "heatmap":
                continue
            x_raw = getattr(tr, "x", None)
            y_raw = getattr(tr, "y", None)
            x = list(x_raw) if x_raw is not None else []
            y = list(y_raw) if y_raw is not None else []
            x_angle = int(settings.get("x_tickangle", 0))
            y_angle = int(settings.get("y_tickangle", 0))
            if x:
                fig.update_xaxes(
                    tickmode="array",
                    tickvals=x,
                    ticktext=[str(v) for v in x],
                    tickangle=x_angle,
                    automargin=True,
                )
            if y:
                fig.update_yaxes(
                    tickmode="array",
                    tickvals=y,
                    ticktext=[str(v) for v in y],
                    tickangle=y_angle,
                    automargin=True,
                )
    except Exception:
        pass
