from ui.charts.natura_icons import get_nature_visual


def test_returns_dedicated_icon_for_each_known_nature():
    color, svg, label = get_nature_visual("criptovalute")
    assert label == "Criptovalute"
    assert svg  # non vuoto

    color2, svg2, _ = get_nature_visual("metalli_miniere")
    assert svg2 != svg  # icona diversa da criptovalute


def test_metalli_miniere_and_commodities_have_distinct_icons():
    """Regressione: con una lookup solo su 'role' (10 valori) queste due
    nature (entrambe satellite_tematico) sarebbero risultate indistinguibili
    - la lookup deve restare su 'nature' (19 valori), non su 'role'."""
    _, svg_metalli, _ = get_nature_visual("metalli_miniere")
    _, svg_commodities, _ = get_nature_visual("commodities")
    assert svg_metalli != svg_commodities


def test_unknown_nature_falls_back_to_diversificata():
    color, svg, label = get_nature_visual("valore_mai_visto")
    assert label == "Esposizione diversificata"


def test_altro_falls_back_to_diversificata():
    _, _, label = get_nature_visual("altro")
    assert label == "Esposizione diversificata"
