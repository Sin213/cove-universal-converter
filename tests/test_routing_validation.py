from cove_converter.routing import SUPPORTED_FORMATS, engine_for


def test_engine_for_rejects_unknown_input() -> None:
    assert engine_for(".unknown", ".pdf") is None


def test_engine_for_rejects_unadvertised_target() -> None:
    assert engine_for(".png", ".exe") is None


def test_engine_for_accepts_advertised_pdf_route() -> None:
    assert engine_for(".docx", ".pdf") == "Pdf"


def test_engine_for_accepts_every_advertised_route() -> None:
    for source, info in SUPPORTED_FORMATS.items():
        for target in info.targets:
            assert engine_for(source, target) is not None, (source, target)


def test_engine_for_normalizes_extension_case() -> None:
    assert engine_for(".PNG", ".JPG") == "Pillow"
