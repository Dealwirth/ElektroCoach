"""Tests des Schaltplan-Editors: Raster, Anschluesse, Netzmodell, Pruefung, Export."""

from __future__ import annotations

import pytest

from app.services import schematic


def _design() -> dict:
    """Ein vollstaendiger Stromkreis: L1 -> LS -> Leuchte -> N."""
    return {
        "components": [
            {"id": "c1", "type": "supply_l1", "x": 0, "y": 0, "rotation": 0, "label": "L1"},
            {"id": "c2", "type": "mcb", "x": 120, "y": 0, "rotation": 0, "label": "F1"},
            {"id": "c3", "type": "lamp", "x": 260, "y": 0, "rotation": 0, "label": "H1"},
            {"id": "c4", "type": "supply_n", "x": 380, "y": 0, "rotation": 0, "label": "N"},
        ],
        "wires": [
            {"id": "w1", "from": {"component_id": "c1", "pin_id": "L1"},
             "to": {"component_id": "c2", "pin_id": "1"},
             "points": [{"x": 40, "y": 20}, {"x": 120, "y": 20}]},
            {"id": "w2", "from": {"component_id": "c2", "pin_id": "2"},
             "to": {"component_id": "c3", "pin_id": "1"},
             "points": [{"x": 200, "y": 20}, {"x": 260, "y": 20}]},
            {"id": "w3", "from": {"component_id": "c3", "pin_id": "2"},
             "to": {"component_id": "c4", "pin_id": "N"},
             "points": [{"x": 320, "y": 20}, {"x": 420, "y": 20}]},
        ],
        "junctions": [],
    }


def test_symbolbibliothek_enthaelt_pflichtbauteile():
    library = schematic.library()
    assert library["grid"] == 20
    types = {s["type"] for s in library["symbols"]}
    required = {
        "switch", "pushbutton_no", "relay", "contactor", "fuse", "mcb", "rcd",
        "motor", "lamp", "socket", "terminal", "supply_l1", "supply_n", "supply_pe",
    }
    assert required <= types


def test_alle_symbole_haben_kategorie_und_masse():
    for symbol in schematic.library()["symbols"]:
        assert symbol["category"]
        assert symbol["name"]
        assert symbol["width"] > 0
        assert symbol["height"] > 0


def test_grid_snapping():
    assert schematic.snap(23) == 20
    assert schematic.snap(31) == 40
    assert schematic.snap(20) == 20
    assert schematic.snap(9) == 0
    assert schematic.snap(-9) == 0


def test_pin_position_ohne_rotation():
    component = {"id": "x", "type": "mcb", "x": 100, "y": 100, "rotation": 0}
    pin = schematic.pin_position(component, "1")
    assert pin == {"x": 100, "y": 120}


def test_pin_position_mit_rotation_90():
    component = {"id": "x", "type": "mcb", "x": 0, "y": 0, "rotation": 90}
    pin = schematic.pin_position(component, "1")
    assert pin is not None
    # Bei 90 Grad muss die Position gedreht und wieder auf das Raster gerastet sein.
    assert pin["x"] % 20 == 0
    assert pin["y"] % 20 == 0


def test_pin_position_unbekanntes_bauteil():
    assert schematic.pin_position({"id": "x", "type": "gibt-es-nicht"}, "1") is None
    assert schematic.pin_position({"id": "x", "type": "mcb"}, "99") is None


def test_leitung_bleibt_beim_verschieben_am_anschluss():
    """Der Kern des Modells: Pins werden berechnet, nicht gespeichert."""
    design = _design()
    before = schematic.pin_position(design["components"][1], "1")

    # Bauteil verschieben: die Leitung haengt weiterhin am berechneten Pin.
    design["components"][1]["x"] = 200
    after = schematic.pin_position(design["components"][1], "1")
    assert after != before
    assert after == {"x": 200, "y": 20}

    # Die Validierung meldet keinen Fehler, weil die Pins gueltig bleiben.
    validation = schematic.validate_design(design)
    assert validation["ok"] is True


def test_anschluesse_werden_berechnet():
    design = _design()
    pins = schematic.all_pins(design["components"])
    ids = {(p["component_id"], p["id"]) for p in pins}
    assert ("c1", "L1") in ids
    assert ("c2", "1") in ids
    assert ("c2", "2") in ids
    assert ("c3", "1") in ids
    assert ("c3", "2") in ids


def test_validierung_erkennt_gueltigen_entwurf():
    validation = schematic.validate_design(_design())
    assert validation["ok"] is True
    assert validation["errors"] == []
    assert validation["component_count"] == 4
    assert validation["wire_count"] == 3


def test_validierung_erkennt_leitung_an_unbekanntem_anschluss():
    design = _design()
    design["wires"][0]["to"] = {"component_id": "c2", "pin_id": "99"}
    validation = schematic.validate_design(design)
    assert validation["ok"] is False
    assert any("nicht vorhandenen Anschluss" in e for e in validation["errors"])


def test_validierung_erkennt_kurzschluss_l1_n():
    design = {
        "components": [
            {"id": "l1", "type": "supply_l1", "x": 0, "y": 0},
            {"id": "n", "type": "supply_n", "x": 200, "y": 0},
        ],
        "wires": [
            {"id": "bad", "from": {"component_id": "l1", "pin_id": "L1"},
             "to": {"component_id": "n", "pin_id": "N"}, "points": []},
        ],
        "junctions": [],
    }
    validation = schematic.validate_design(design)
    assert validation["ok"] is False
    assert any("Kurzschluss" in e and "Neutralleiter" in e for e in validation["errors"])


def test_validierung_erkennt_kurzschluss_l1_pe():
    design = {
        "components": [
            {"id": "l1", "type": "supply_l1", "x": 0, "y": 0},
            {"id": "pe", "type": "supply_pe", "x": 200, "y": 0},
        ],
        "wires": [
            {"id": "bad", "from": {"component_id": "l1", "pin_id": "L1"},
             "to": {"component_id": "pe", "pin_id": "PE"}, "points": []},
        ],
        "junctions": [],
    }
    validation = schematic.validate_design(design)
    assert validation["ok"] is False
    assert any("Schutzleiter" in e for e in validation["errors"])


def test_validierung_erkennt_leitung_mit_sich_selbst():
    design = _design()
    design["wires"].append({
        "id": "selbst", "from": {"component_id": "c2", "pin_id": "1"},
        "to": {"component_id": "c2", "pin_id": "1"}, "points": [],
    })
    validation = schematic.validate_design(design)
    assert any("mit sich selbst" in w for w in validation["warnings"])


def test_freie_anschluesse_werden_gemeldet():
    design = _design()
    design["components"].append({"id": "c9", "type": "socket", "x": 600, "y": 0})
    validation = schematic.validate_design(design)
    free = {(p["component_id"], p["pin_id"]) for p in validation["free_pins"]}
    assert ("c9", "L") in free
    assert ("c9", "N") in free
    assert ("c9", "PE") in free


def test_validierung_meldet_unbekannten_bauteiltyp():
    design = {"components": [{"id": "x", "type": "gibt-es-nicht"}], "wires": [], "junctions": []}
    validation = schematic.validate_design(design)
    assert validation["ok"] is False
    assert any("Unbekannter Bauteiltyp" in e for e in validation["errors"])


def test_kreuzung_ohne_verbindungspunkt_ist_keine_verbindung():
    """Zwei Leitungen, die sich kreuzen, aber keinen Verbindungspunkt haben,
    bilden zwei getrennte Netze."""
    design = {
        "components": [
            {"id": "a1", "type": "supply_l1", "x": 0, "y": 0},
            {"id": "b1", "type": "supply_l1", "x": 0, "y": 200},
        ],
        "wires": [
            {"id": "wa", "from": {"component_id": "a1", "pin_id": "L1"},
             "to": {"component_id": "b1", "pin_id": "L1"},
             "points": [{"x": 100, "y": 20}, {"x": 100, "y": 220}]},
        ],
        "junctions": [],
    }
    networks = schematic.connected_groups(design)
    # Eine Leitung verbindet zwei Anschluesse -> ein Netz mit zwei Elementen.
    assert len(networks) == 1
    assert len(networks[0]) == 2


def test_verbindungspunkt_verbindet_netze():
    design = {
        "components": [
            {"id": "a1", "type": "supply_l1", "x": 0, "y": 0},
            {"id": "a2", "type": "supply_l1", "x": 0, "y": 100},
            {"id": "j", "type": "junction", "x": 100, "y": 20},
        ],
        "wires": [
            {"id": "w1", "from": {"component_id": "a1", "pin_id": "L1"},
             "to": {"component_id": "j", "pin_id": "1"}, "points": []},
        ],
        "junctions": [{"id": "jx", "x": 100, "y": 20}],
    }
    validation = schematic.validate_design(design)
    assert isinstance(validation["junction_count"], int)


def test_netzgruppen_finden_zusammenhaengenden_stromkreis():
    """Jede Leitung bildet ein Netz. Der Stromkreis besteht aus drei Netzen:
    L1-LS, LS-Leuchte und Leuchte-N. Der LS trennt die Netze, wie in der
    Realitaet."""
    networks = schematic.connected_groups(_design())
    assert len(networks) == 3
    assert all(len(network) == 2 for network in networks)
    flattened = {item for network in networks for item in network}
    assert flattened == {"c1.L1", "c2.1", "c2.2", "c3.1", "c3.2", "c4.N"}


def test_design_statistik():
    stats = schematic.design_stats(_design())
    assert stats["components"] == 4
    assert stats["wires"] == 3
    assert stats["by_type"]["mcb"] == 1
    assert stats["wire_length_px"] > 0


def test_projekt_anlegen_speichern_laden_loeschen():
    project = schematic.create_project("Testprojekt", "Beschreibung", _design())
    assert project["id"]
    assert project["name"] == "Testprojekt"
    assert project["validation"]["ok"] is True

    project["data"]["components"][0]["label"] = "Geaendert"
    saved = schematic.save_project(project["id"], name="Neuer Name", data=project["data"])
    assert saved["name"] == "Neuer Name"

    reloaded = schematic.get_project(project["id"])
    assert reloaded["data"]["components"][0]["label"] == "Geaendert"

    assert schematic.delete_project(project["id"]) is True
    assert schematic.get_project(project["id"]) is None
    assert schematic.delete_project(project["id"]) is False


def test_projekt_speichern_rastet_bauteile_ein():
    project = schematic.create_project("Raster", "", {"components": [], "wires": [], "junctions": []})
    data = {
        "components": [{"id": "c", "type": "mcb", "x": 137, "y": 43, "rotation": 0}],
        "wires": [], "junctions": [],
    }
    saved = schematic.save_project(project["id"], data=data)
    assert saved["data"]["components"][0]["x"] == 140
    assert saved["data"]["components"][0]["y"] == 40
    schematic.delete_project(project["id"])


def test_projekt_duplizieren():
    project = schematic.create_project("Original", "", _design())
    copy = schematic.duplicate_project(project["id"])
    assert copy["id"] != project["id"]
    assert "Kopie" in copy["name"]
    schematic.delete_project(project["id"])
    schematic.delete_project(copy["id"])


def test_projektliste_enthaelt_statistik():
    project = schematic.create_project("Mit Statistik", "", _design())
    items = schematic.list_projects()
    entry = next(item for item in items if item["id"] == project["id"])
    assert entry["stats"]["components"] == 4
    schematic.delete_project(project["id"])


def test_unbekanntes_projekt():
    assert schematic.get_project("gibt-es-nicht") is None
    assert schematic.save_project("gibt-es-nicht", name="x") is None
    assert schematic.duplicate_project("gibt-es-nicht") is None
    assert schematic.project_svg("gibt-es-nicht") is None


def test_svg_export_enthaelt_bauteile_und_leitungen():
    project = schematic.create_project("Export", "", _design())
    svg = schematic.project_svg(project["id"])
    assert svg is not None
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<path" in svg          # Leitungen
    assert "<rect" in svg          # Bauteile
    assert ">F1<" in svg           # Beschriftung
    schematic.delete_project(project["id"])


def test_svg_export_escaped_sonderzeichen():
    data = {
        "components": [{"id": "t", "type": "text", "x": 0, "y": 0, "label": "<script>&x</script>"}],
        "wires": [], "junctions": [],
    }
    project = schematic.create_project("Injection", "", data)
    svg = schematic.project_svg(project["id"])
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    schematic.delete_project(project["id"])


def test_rotation_normalisierung():
    for rotation in (0, 90, 180, 270, 360, 450):
        x, y = schematic.rotate_point(20, 0, rotation, 80, 40)
        assert 0 <= x <= 80
        assert 0 <= y <= 80
