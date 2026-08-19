from core.services.sator import CAP_MORBIDO_NATURA, SATOR_NATURE_VALUES


def test_cap_morbido_natura_covers_crypto_defense_single_country():
    assert "criptovalute" in CAP_MORBIDO_NATURA
    assert "difesa_sicurezza" in CAP_MORBIDO_NATURA
    assert "azionario_paese_singolo" in CAP_MORBIDO_NATURA
    assert CAP_MORBIDO_NATURA["criptovalute"] == 0.05
    assert CAP_MORBIDO_NATURA["difesa_sicurezza"] == 0.06
    assert CAP_MORBIDO_NATURA["azionario_paese_singolo"] == 0.08


def test_sator_nature_values_includes_new_entries():
    assert "criptovalute" in SATOR_NATURE_VALUES
    assert "difesa_sicurezza" in SATOR_NATURE_VALUES
    assert "azionario_paese_singolo" in SATOR_NATURE_VALUES
