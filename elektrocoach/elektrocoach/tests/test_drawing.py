"""Tests for the schematic editor backend: model, validation, export, library.

The editor keeps the graphical drawing and the electrical model separate. These
tests cover that separation: validation must rely on electrical connections and
must not be fooled by drawn lines alone.
"""

from __future__ import annotations

import pytest


# -- symbol library ----------------------------------------------------------

def test_library_is_populated_and_well_formed():
    from elektrocoach.drawing.symbols import library_as_list

    library = library_as_list()
    assert len(library) >= 25, "the symbol library is suspiciously small"
    for symbol in library:
        assert symbol["id"]
        assert symbol["name"]
        assert symbol["category"]
        assert symbol["width"] > 0 and symbol["height"] > 0
        assert symbol["shapes"], f"{symbol['id']} has no drawing shapes"
        assert symbol["terminals"], f"{symbol['id']} has no terminals"
        for terminal in symbol["terminals"]:
            assert terminal["id"]
            assert isinstance(terminal["x"], (int, float))
            assert isinstance(terminal["y"], (int, float))


def test_library_covers_the_required_categories():
    from elektrocoach.drawing.symbols import library_as_list

    categories = {symbol["category"] for symbol in library_as_list()}
    for expected in ("Passive Bauelemente", "Schutzgeräte", "Schaltgeräte"):
        assert expected in categories, f"category {expected} missing"


def test_symbol_lookup_and_search():
    from elektrocoach.drawing.symbols import get_symbol, search

    assert get_symbol("resistor") is not None
    assert get_symbol("does-not-exist") is None
    assert search("Sicherung"), "searching for a German term found nothing"


# -- model normalisation -----------------------------------------------------

def test_normalise_document_fills_defaults_and_drops_garbage():
    from elektrocoach.drawing.model import normalise_document

    document = normalise_document({
        "components": [
            {"id": "C1", "symbol": "resistor", "x": 2, "y": 3, "rotation": 450},
            {"id": "C2", "symbol": "lamp", "x": 8, "y": 3},
            {"symbol": "resistor"},  # no id -> must be dropped
            "not-a-dict",
            {"id": "C3", "symbol": "gibtsnicht", "x": 0, "y": 0},  # bad symbol
        ],
        "connections": [
            {"from": {"component": "C1", "terminal": "1"},
             "to": {"component": "C2", "terminal": "2"}},
            {"from": {"component": "C1", "terminal": "1"},
             "to": {"component": "UNKNOWN", "terminal": "2"}},  # dropped
            {"broken": True},
        ],
        "wires": [{"points": [[0, 0], [20, 0]]}],
    })
    assert len(document["components"]) == 2
    component = document["components"][0]
    assert component["id"] == "C1"
    # Rotation is normalised into 0/90/180/270.
    assert component["rotation"] in (0, 90, 180, 270)
    # Only the connection between two known components survives.
    assert len(document["connections"]) == 1
    assert len(document["wires"]) == 1
    assert document["grid"] > 0


def test_normalise_document_is_idempotent():
    from elektrocoach.drawing.model import normalise_document

    payload = {
        "components": [{"id": "C1", "symbol": "lamp", "x": 4, "y": 4}],
        "connections": [],
    }
    once = normalise_document(payload)
    twice = normalise_document(once)
    assert once == twice


def test_normalise_document_handles_empty_input():
    from elektrocoach.drawing.model import normalise_document

    document = normalise_document(None)
    assert document["components"] == []
    assert document["connections"] == []


# -- validation --------------------------------------------------------------

def test_validation_flags_unknown_symbol():
    from elektrocoach.drawing.model import validate

    report = validate({"components": [{"id": "C1", "symbol": "unbekannt", "x": 0, "y": 0}]})
    assert report.ok is False
    assert any(issue.code == "unknown_symbol" for issue in report.issues)


def test_validation_flags_unknown_terminal():
    from elektrocoach.drawing.model import validate

    report = validate({
        "components": [{"id": "C1", "symbol": "resistor", "x": 0, "y": 0},
                       {"id": "C2", "symbol": "resistor", "x": 6, "y": 0}],
        "connections": [{"from": {"component": "C1", "terminal": "99"},
                         "to": {"component": "C2", "terminal": "1"}}],
    })
    assert any(issue.code == "unknown_terminal" for issue in report.issues)


def test_validation_flags_self_connection():
    from elektrocoach.drawing.model import validate

    report = validate({
        "components": [{"id": "C1", "symbol": "resistor", "x": 0, "y": 0}],
        "connections": [{"from": {"component": "C1", "terminal": "1"},
                         "to": {"component": "C1", "terminal": "1"}}],
    })
    assert any(issue.code == "self_connection" for issue in report.issues)


def test_validation_flags_duplicate_connection_as_warning():
    from elektrocoach.drawing.model import validate

    report = validate({
        "components": [{"id": "C1", "symbol": "resistor", "x": 0, "y": 0},
                       {"id": "C2", "symbol": "resistor", "x": 6, "y": 0}],
        "connections": [
            {"from": {"component": "C1", "terminal": "1"},
             "to": {"component": "C2", "terminal": "1"}},
            {"from": {"component": "C2", "terminal": "1"},
             "to": {"component": "C1", "terminal": "1"}},
        ],
    })
    assert any(issue.code == "duplicate_connection" for issue in report.issues)
    assert report.counts["warning"] >= 1


def test_validation_detects_short_circuit_between_l_and_n():
    from elektrocoach.drawing.model import validate

    # The distribution board exposes L and N terminals; wiring them together
    # directly is a short circuit.
    report = validate({
        "components": [
            {"id": "SRC", "symbol": "distribution", "x": 0, "y": 0},
            {"id": "LOAD", "symbol": "lamp", "x": 8, "y": 0},
        ],
        "connections": [
            {"from": {"component": "SRC", "terminal": "in_l"},
             "to": {"component": "SRC", "terminal": "in_n"}},
            {"from": {"component": "SRC", "terminal": "out1"},
             "to": {"component": "LOAD", "terminal": "1"}},
        ],
    })
    assert any(issue.code == "short_circuit" for issue in report.issues)


def test_drawn_wire_alone_does_not_create_an_electrical_connection():
    """The graphical layer and the electrical layer must stay separate."""

    from elektrocoach.drawing.model import netlist, validate

    document = {
        "components": [{"id": "C1", "symbol": "resistor", "x": 0, "y": 0},
                       {"id": "C2", "symbol": "resistor", "x": 6, "y": 0}],
        # A line is drawn between the parts, but no connection is declared.
        "wires": [{"id": "W1", "points": [[0, 0], [120, 0]]}],
        "connections": [],
    }
    report = validate(document)
    # No short circuit may be inferred from a drawn line.
    assert not any(issue.code == "short_circuit" for issue in report.issues)
    nets = netlist(document)
    # Each of the four terminals stays its own net: the drawn line does not merge
    # them, because only declared connections carry electrical meaning.
    assert len(nets["nets"]) == 4


def test_netlist_merges_connected_terminals():
    from elektrocoach.drawing.model import netlist

    nets = netlist({
        "components": [{"id": "C1", "symbol": "resistor", "x": 0, "y": 0},
                       {"id": "C2", "symbol": "resistor", "x": 6, "y": 0},
                       {"id": "C3", "symbol": "resistor", "x": 12, "y": 0}],
        "connections": [
            {"from": {"component": "C1", "terminal": "2"},
             "to": {"component": "C2", "terminal": "1"}},
            {"from": {"component": "C2", "terminal": "2"},
             "to": {"component": "C3", "terminal": "1"}},
        ],
    })
    # Three two-terminal components chained with two links form four nets:
    # {C1.1}, {C1.2, C2.1}, {C2.2, C3.1}, {C3.2}.
    assert len(nets["nets"]) == 4
    sizes = sorted(len(net["terminals"]) for net in nets["nets"])
    assert sizes == [1, 1, 2, 2]


def test_validation_counts_are_consistent():
    from elektrocoach.drawing.model import validate

    report = validate({
        "components": [{"id": "C1", "symbol": "unbekannt", "x": 0, "y": 0}],
        "connections": [],
    })
    total = sum(report.counts.values())
    assert total == len(report.issues)
    payload = report.as_dict()
    assert payload["ok"] is False
    assert payload["counts"]["error"] >= 1


# -- export ------------------------------------------------------------------

def sample_document():
    from elektrocoach.drawing.model import normalise_document

    return normalise_document({
        "components": [
            {"id": "F1", "symbol": "breaker", "x": 2, "y": 2, "label": "F1"},
            {"id": "L1", "symbol": "lamp", "x": 8, "y": 2, "label": "H1"},
        ],
        "connections": [{"from": {"component": "F1", "terminal": "2"},
                         "to": {"component": "L1", "terminal": "1"}}],
        "wires": [{"points": [[0, 3], [2, 3]]}],
        "texts": [{"id": "T1", "x": 0, "y": -1, "text": "Beleuchtung"}],
    })


def test_svg_export_is_well_formed_xml():
    from xml.etree import ElementTree

    from elektrocoach.drawing.exporter import to_svg

    svg = to_svg(sample_document())
    assert svg.startswith("<?xml")
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert "F1" in svg
    assert "Beleuchtung" in svg


def test_svg_export_escapes_untrusted_labels():
    """A label must never be able to inject markup into the exported file."""

    from elektrocoach.drawing.exporter import to_svg
    from elektrocoach.drawing.model import normalise_document

    document = normalise_document({
        "components": [{"id": "C1", "symbol": "resistor", "x": 0, "y": 0,
                        "label": "<script>alert(1)</script>"}],
    })
    svg = to_svg(document)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_pdf_export_has_pdf_header_and_trailer():
    from elektrocoach.drawing.exporter import to_pdf

    pdf = to_pdf(sample_document())
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf


def test_pdf_export_handles_an_empty_document():
    from elektrocoach.drawing.exporter import to_pdf, to_svg

    empty = {"components": [], "connections": [], "wires": [], "texts": []}
    assert to_pdf(empty).startswith(b"%PDF-")
    assert to_svg(empty).startswith("<?xml")


def test_export_never_crashes_on_a_broken_component():
    from elektrocoach.drawing.exporter import to_pdf, to_svg

    broken = {"components": [{"id": "X", "symbol": "gibtsnicht", "x": 0, "y": 0}],
              "connections": [{"from": {"component": "X", "terminal": "1"},
                               "to": {"component": "Y", "terminal": "2"}}],
              "wires": [{"points": []}]}
    # Neither export may raise; an incomplete drawing is still exportable.
    assert to_svg(broken).startswith("<?xml")
    assert to_pdf(broken).startswith(b"%PDF-")
