"""The pinned font set (§1 rule 9): the fonts a card is measured and
printed in, shipped with the service so a render never depends on what a
server happens to have installed. OFL-licensed (fonts/OFL.txt)."""

from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "fonts"

FACES = {
    "IBM Plex Sans": {400: "IBMPlexSans-Regular.ttf", 500: "IBMPlexSans-Medium.ttf",
                      600: "IBMPlexSans-SemiBold.ttf", 700: "IBMPlexSans-Bold.ttf"},
    "IBM Plex Mono": {400: "IBMPlexMono-Regular.ttf", 500: "IBMPlexMono-Medium.ttf"},
    "Noto Sans Bengali": {400: "NotoSansBengali-Regular.ttf", 500: "NotoSansBengali-Medium.ttf",
                          600: "NotoSansBengali-SemiBold.ttf", 700: "NotoSansBengali-Bold.ttf"},
}
FAMILIES = tuple(FACES)


def family(name):
    return name if name in FACES else "IBM Plex Sans"


def weight(fam, w):
    """The nearest weight the pinned set has."""
    have = sorted(FACES[family(fam)])
    w = int(w or 400)
    return min(have, key=lambda x: (abs(x - w), -x))


def font_face_css():
    return "".join(
        f"@font-face{{font-family:'{fam}';src:url('file://{DIR / file}');font-weight:{w};font-style:normal;}}"
        for fam, weights in FACES.items() for w, file in weights.items())


def stack(fam):
    """Bangla in a Latin face falls back to Noto Sans Bengali, never boxes."""
    return f"'{family(fam)}', 'Noto Sans Bengali'"
