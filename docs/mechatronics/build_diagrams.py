"""Generate the mechatronics project diagrams as standalone SVG files.

Run:  python3 docs/mechatronics/build_diagrams.py
Writes fig1-system-layout.svg, fig2-control-block-diagram.svg and
fig3-operating-sequence.svg next to this script.
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent

INK = "#1d2733"
MUTED = "#5b6876"
PAPER = "#ffffff"
PART = "#eef1f4"
PART2 = "#f6f8fa"
BLUE = "#2a77b5"
FLUID = "#d9eaf7"
FLUID2 = "#b9d7ef"
RED = "#d2452f"
RED_T = "#fcebe6"
RED_T2 = "#f7d6cd"
AMBER = "#b7791f"
FAULT = "#b42318"
FAULT_T = "#fdeceb"
SEAL = "#3a4654"
FONT = "Helvetica, Arial, sans-serif"
MONO = "Menlo, Consolas, 'Courier New', monospace"


def t(x, y, s, size=12, weight=None, fill=INK, anchor="start", family=None, spacing=None):
    attrs = f'x="{x}" y="{y}" font-size="{size}" fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    if family:
        attrs += f' font-family="{family}"'
    if spacing:
        attrs += f' letter-spacing="{spacing}"'
    return f"<text {attrs}>{escape(s)}</text>"


def marker(mid, color, size):
    return (
        f'<marker id="{mid}" viewBox="0 0 10 10" refX="8" refY="5" markerUnits="userSpaceOnUse" '
        f'markerWidth="{size}" markerHeight="{size}" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
    )


def line(x1, y1, x2, y2, color=INK, width=1.8, mk=None, dash=None):
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"'
    if dash:
        s += f' stroke-dasharray="{dash}"'
    if mk:
        s += f' marker-end="url(#{mk})"'
    return s + "/>"


def path(d, color=INK, width=1.8, mk=None, dash=None, fill="none"):
    s = f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"'
    if dash:
        s += f' stroke-dasharray="{dash}"'
    if mk:
        s += f' marker-end="url(#{mk})"'
    return s + "/>"


def svg_doc(w, h, title, label, defs, body):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="{escape(label)}" font-family="{FONT}">\n'
        f"<title>{escape(title)}</title>\n"
        f"<defs>{''.join(defs)}</defs>\n"
        f'<rect width="{w}" height="{h}" fill="{PAPER}"/>\n'
        f'<rect x="12" y="12" width="{w - 24}" height="{h - 24}" fill="none" stroke="{INK}" stroke-width="1.5"/>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


def balloon(n, cx, cy, tx, ty, r=14, size=13):
    return "\n".join([
        line(cx, cy, tx, ty, INK, 1.1),
        f'<circle cx="{tx}" cy="{ty}" r="2.6" fill="{INK}"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{PAPER}" stroke="{INK}" stroke-width="1.5"/>',
        t(cx, cy + size * 0.36, str(n), size, "700", anchor="middle"),
    ])


def title_strip(x, y, w, fig, sheet):
    """Compact three-row title block used on figs 2 and 3 (84 px tall)."""
    return "\n".join([
        f'<rect x="{x}" y="{y}" width="{w}" height="84" fill="{PAPER}" stroke="{INK}" stroke-width="1.2"/>',
        line(x, y + 28, x + w, y + 28, INK, 0.8),
        line(x, y + 56, x + w, y + 56, INK, 0.8),
        t(x + 12, y + 19, "MECHATRONICS PROJECT", 12, "700", spacing="0.6"),
        t(x + 12, y + 47, fig, 12),
        t(x + w - 12, y + 47, "NTS", 11, fill=MUTED, anchor="end"),
        t(x + 12, y + 75, f"Sheet {sheet} of 3 · Rev A · 2026-10-14", 11, fill=MUTED),
    ])


# ---------------------------------------------------------------- Fig. 1
def fig1():
    W, H = 1280, 860
    defs = [
        marker("ah-red", RED, 16),
        marker("ah-blue", BLUE, 11),
        marker("ah-red-s", RED, 11),
    ]
    # Detail A column outline (zig-zag break at the bottom) reused for clipping
    zig = "".join(f" l13 {-6 if i % 2 == 0 else 6}" for i in range(8))
    detail_col = f"M188 714 V806{zig} V714 Z"
    defs.append(f'<clipPath id="clipA"><path d="{detail_col}"/></clipPath>')

    b = []
    b.append(t(40, 54, "Mechatronics Project · System Layout", 24, "700"))
    b.append(t(40, 78, "Fig. 1 — Reservoir, feed line and sliding-collar column, redrawn from the concept sketch. Not to scale.", 13, fill=MUTED))

    # 1 Tank with fluid
    b.append(f'<path d="M140 260 V520 A80 18 0 0 0 300 520 V260 Z" fill="{FLUID}"/>')
    b.append(f'<ellipse cx="220" cy="260" rx="80" ry="18" fill="{FLUID2}" stroke="{BLUE}" stroke-width="1.2"/>')
    b.append(path("M140 150 V520 A80 18 0 0 0 300 520 V150", INK, 2.5))
    # 2 Lid
    b.append(f'<path d="M126 140 V154 A94 22 0 0 0 314 154 V140 Z" fill="{PART}" stroke="{INK}" stroke-width="2"/>')
    b.append(f'<ellipse cx="220" cy="140" rx="94" ry="22" fill="{PART2}" stroke="{INK}" stroke-width="2"/>')
    b.append(f'<rect x="206" y="112" width="28" height="18" rx="4" fill="{PART}" stroke="{INK}" stroke-width="2"/>')
    # 3 Float level sensor
    b.append(line(276, 178, 276, 300, INK, 1.6))
    b.append(f'<rect x="266" y="250" width="20" height="14" rx="4" fill="{PAPER}" stroke="{INK}" stroke-width="1.6"/>')
    # 4 Outlet stub + solenoid valve
    b.append(f'<rect x="300" y="313" width="38" height="14" fill="{FLUID}" stroke="{INK}" stroke-width="1.8"/>')
    b.append(path("M338 304 L356 320 L338 336 Z M374 304 L356 320 L374 336 Z", INK, 1.8, fill=PAPER))
    b.append(line(356, 320, 356, 298, INK, 1.8))
    b.append(f'<rect x="343" y="280" width="26" height="18" fill="{PART}" stroke="{INK}" stroke-width="1.8"/>')
    b.append(line(343, 298, 369, 280, INK, 1.2))
    # 5 Feed hose (outline + fluid core)
    hose = "M374 320 H420 C480 320 520 250 580 250 H668"
    b.append(f'<path d="{hose}" fill="none" stroke="{INK}" stroke-width="15"/>')
    b.append(f'<path d="{hose}" fill="none" stroke="{FLUID}" stroke-width="10"/>')
    b.append(line(590, 226, 638, 226, BLUE, 2, "ah-blue"))
    b.append(t(614, 216, "feed", 12, fill=BLUE, anchor="middle"))

    # 7 Guide column
    b.append(f'<rect x="694" y="268" width="52" height="332" fill="{PART}" stroke="{INK}" stroke-width="2.5"/>')
    # 8 Sliding collar (current position, drawn in the moving-part tint)
    b.append(f'<path d="M660 420 V432 A60 12 0 0 0 780 432 V420 Z" fill="{RED_T2}" stroke="{INK}" stroke-width="2"/>')
    b.append(f'<ellipse cx="720" cy="420" rx="60" ry="12" fill="{RED_T}" stroke="{INK}" stroke-width="2"/>')
    b.append(f'<rect x="694" y="404" width="52" height="16" fill="{PART}"/>')
    b.append(line(694, 404, 694, 420, INK, 2.5))
    b.append(line(746, 404, 746, 420, INK, 2.5))
    b.append(path("M694 420 A26 5 0 0 0 746 420", INK, 1.5))
    # Hidden fluid bore through the column
    b.append(line(713, 270, 713, 598, BLUE, 1.2, dash="6 4"))
    b.append(line(727, 270, 727, 598, BLUE, 1.2, dash="6 4"))
    # Phantom collar at both stroke ends
    for y in (330, 510):
        b.append(path(f"M660 {y} V{y + 12} A60 12 0 0 0 780 {y + 12} V{y}", RED, 1.4, dash="12 4 3 4"))
        b.append(f'<ellipse cx="720" cy="{y}" rx="60" ry="12" fill="none" stroke="{RED}" stroke-width="1.4" stroke-dasharray="12 4 3 4"/>')
    b.append(t(650, 334, "stroke top", 11, fill=RED, anchor="end"))
    b.append(t(650, 516, "stroke bottom", 11, fill=RED, anchor="end"))
    # Stroke direction arrows (as in the sketch: up on the left, down on the right)
    b.append(line(640, 460, 640, 364, RED, 3, "ah-red"))
    b.append(line(800, 364, 800, 460, RED, 3, "ah-red"))

    # 6 Top head with seal
    b.append(f'<rect x="688" y="268" width="64" height="6" fill="{SEAL}"/>')
    b.append(f'<polygon points="680,232 760,232 774,250 760,268 680,268 666,250" fill="{PART}" stroke="{INK}" stroke-width="2.5" stroke-linejoin="round"/>')
    b.append(line(700, 232, 700, 268, INK, 1.1))
    b.append(line(740, 232, 740, 268, INK, 1.1))

    # 9 Base housing with hidden internals, 10 port
    b.append(f'<path d="M610 600 H830 C858 636 868 700 842 738 Q822 766 720 766 Q618 766 598 738 C572 700 582 636 610 600 Z" fill="{PART}" stroke="{INK}" stroke-width="2.5"/>')
    b.append(f'<rect x="636" y="622" width="58" height="42" rx="3" fill="none" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    b.append(f'<rect x="708" y="622" width="96" height="42" rx="3" fill="none" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    b.append(line(694, 643, 708, 643, MUTED, 1.2, dash="5 4"))
    b.append(t(665, 647, "M1", 11, fill=MUTED, anchor="middle"))
    b.append(t(756, 647, "MCU · driver", 11, fill=MUTED, anchor="middle"))
    b.append(f'<ellipse cx="770" cy="724" rx="17" ry="8" fill="{PAPER}" stroke="{INK}" stroke-width="2"/>')
    b.append(f'<ellipse cx="770" cy="724" rx="6" ry="3" fill="{INK}"/>')

    # Detail A marker on the main view
    b.append(f'<circle cx="720" cy="252" r="64" fill="none" stroke="{INK}" stroke-width="1.2" stroke-dasharray="14 4 3 4"/>')
    b.append(t(662, 202, "A", 15, "700"))

    # Balloons
    for n, cx, cy, tx, ty in [
        (1, 80, 430, 140, 430),
        (2, 80, 110, 128, 147),
        (3, 340, 200, 285, 254),
        (4, 410, 268, 369, 288),
        (5, 500, 352, 500, 292),
        (6, 880, 226, 772, 246),
        (7, 880, 300, 746, 300),
        (8, 872, 566, 762, 436),
        (9, 900, 660, 856, 676),
        (10, 900, 736, 787, 726),
    ]:
        b.append(balloon(n, cx, cy, tx, ty))

    # Detail A: head, seal and column top enlarged x2
    b.append(t(70, 606, "DETAIL A", 13, "700", spacing="0.8"))
    b.append(t(146, 606, "head, seal and column top · enlarged ×2", 12, fill=MUTED))
    b.append(f'<rect x="92" y="651" width="50" height="30" fill="{FLUID}" stroke="{INK}" stroke-width="2"/>')
    b.append(f'<path d="{detail_col}" fill="{PART}"/>')
    knurl = []
    for k in range(-100, 300, 12):
        knurl.append(line(188 + k, 714, 188 + k + 92, 806, MUTED, 0.8))
        knurl.append(line(188 + k + 92, 714, 188 + k, 806, MUTED, 0.8))
    b.append(f'<g clip-path="url(#clipA)" opacity="0.55">{"".join(knurl)}</g>')
    b.append(path(detail_col, INK, 2.5))
    b.append(f'<rect x="176" y="702" width="128" height="12" fill="{SEAL}"/>')
    b.append(f'<polygon points="160,630 320,630 348,666 320,702 160,702 132,666" fill="{PART}" stroke="{INK}" stroke-width="2.5" stroke-linejoin="round"/>')
    b.append(line(200, 630, 200, 702, INK, 1.1))
    b.append(line(280, 630, 280, 702, INK, 1.1))
    # Internal passage: hose -> head -> bore (hidden lines)
    b.append(path("M134 656 H254 V804", BLUE, 1.4, dash="6 4"))
    b.append(path("M134 676 H226 V804", BLUE, 1.4, dash="6 4"))
    b.append(line(240, 690, 240, 740, BLUE, 1.8, "ah-blue"))
    # Detail callouts
    b.append(t(70, 704, "feed hose (5)", 11.5, fill=MUTED))
    for (x1, y1), y_text, label in [
        ((348, 666), 670, "top head (6)"),
        ((304, 708), 712, "seal ring"),
        ((292, 752), 756, "knurled column surface (7)"),
        ((254, 790), 794, "fluid bore (hidden)"),
    ]:
        b.append(line(x1, y1, 362, y1, INK, 1))
        b.append(f'<circle cx="{x1}" cy="{y1}" r="2.2" fill="{INK}"/>')
        b.append(t(368, y_text, label, 11.5, fill=MUTED))

    # Parts list
    b.append(f'<rect x="960" y="96" width="296" height="470" fill="{PAPER}" stroke="{INK}" stroke-width="1.2"/>')
    b.append(t(972, 114, "PARTS LIST", 10.5, "700", MUTED, spacing="1"))
    b.append(line(960, 122, 1256, 122, INK, 0.8))
    parts = [
        ("Reservoir tank", "holds the working fluid"),
        ("Lid / fill cap", "removable, for refilling"),
        ("Level sensor", "float switch, low-level signal"),
        ("Solenoid valve V1", "12 V, opens / closes the feed"),
        ("Feed hose", "flexible tube, tank → head"),
        ("Top head", "hose fitting, seals column top"),
        ("Guide column", "hollow tube, guides the collar"),
        ("Sliding collar", "moving carriage, strokes up / down"),
        ("Base housing", "holds M1, MCU, driver, PSU"),
        ("Base port", "outlet / drain (or status LED)"),
    ]
    for i, (name, note) in enumerate(parts):
        top = 122 + i * 44
        b.append(f'<circle cx="982" cy="{top + 22}" r="11" fill="{PAPER}" stroke="{INK}" stroke-width="1.3"/>')
        b.append(t(982, top + 26, str(i + 1), 11, "700", anchor="middle"))
        b.append(t(1004, top + 19, name, 12.5, "700"))
        b.append(t(1004, top + 35, note, 11.5, fill=MUTED))
        if i < len(parts) - 1:
            b.append(line(966, top + 44, 1250, top + 44, PART, 1))

    # Legend
    b.append(f'<rect x="960" y="580" width="296" height="124" fill="{PAPER}" stroke="{INK}" stroke-width="1.2"/>')
    b.append(t(972, 598, "LEGEND", 10.5, "700", MUTED, spacing="1"))
    b.append(line(972, 618, 1002, 618, RED, 2.5, "ah-red-s"))
    b.append(t(1016, 622, "motion — stroke direction", 11.5))
    b.append(line(972, 640, 1004, 640, RED, 1.4, dash="12 4 3 4"))
    b.append(t(1016, 644, "phantom — stroke end positions", 11.5))
    b.append(f'<rect x="972" y="656" width="32" height="12" fill="{FLUID}" stroke="{BLUE}" stroke-width="1.2"/>')
    b.append(t(1016, 666, "working fluid / flow", 11.5))
    b.append(f'<rect x="972" y="678" width="32" height="12" fill="none" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    b.append(t(1016, 688, "hidden — inside housing or bore", 11.5))

    # Title block
    b.append(f'<rect x="960" y="716" width="296" height="120" fill="{PAPER}" stroke="{INK}" stroke-width="1.5"/>')
    for y in (746, 776, 806):
        b.append(line(960, y, 1256, y, INK, 0.8))
    b.append(line(1108, 776, 1108, 836, INK, 0.8))
    b.append(t(972, 736, "MECHATRONICS PROJECT", 13, "700", spacing="0.6"))
    b.append(t(972, 766, "Fig. 1 · System layout", 12.5))
    b.append(t(972, 796, "Scale: NTS", 12))
    b.append(t(1120, 796, "Sheet 1 of 3", 12))
    b.append(t(972, 826, "Rev A · 2026-10-14", 12))
    b.append(t(1120, 826, "Drawn: ____________", 12, fill=MUTED))

    label = (
        "Mechanical layout: a reservoir tank with lid and float level sensor feeds a solenoid valve "
        "and flexible hose into the top head of a vertical guide column. A sliding collar strokes up "
        "and down the column between two end positions. The column stands on a base housing that "
        "holds the motor and electronics and has an outlet port. Detail A enlarges the head, seal "
        "and column top."
    )
    return svg_doc(W, H, "Fig. 1 – System layout", label, defs, b)


# ---------------------------------------------------------------- Fig. 2
def block(x, y, w, h, title, sub, fill=PART2, stroke=INK, title_fill=INK):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>']
    if sub:
        out.append(t(x + 14, y + h / 2 - 3, title, 13.5, "700", title_fill))
        out.append(t(x + 14, y + h / 2 + 15, sub, 11.5, fill=MUTED))
    else:
        out.append(t(x + 14, y + h / 2 + 5, title, 13.5, "700", title_fill))
    return "\n".join(out)


def fig2():
    W, H = 1280, 840
    defs = [
        marker("ah", INK, 11),
        marker("ah-amber", AMBER, 11),
        marker("ah-blue", BLUE, 11),
        marker("ah-red", RED, 12),
    ]
    b = []
    b.append(t(40, 54, "Control System · Block Diagram", 24, "700"))
    b.append(t(40, 78, "Fig. 2 — Signals and power between the sensors, the controller and the actuators. Numbers refer to Fig. 1.", 13, fill=MUTED))

    # Column headings
    for x, s in [(56, "INPUTS"), (380, "CONTROLLER"), (720, "DRIVERS"), (1040, "ACTUATORS")]:
        b.append(t(x, 198, s, 10.5, "700", MUTED, spacing="1"))
    b.append(t(56, 620, "MECHANISM  (parts from Fig. 1)", 10.5, "700", MUTED, spacing="1"))

    # Power row
    b.append(block(380, 100, 220, 52, "5 V regulator", "buck converter, 12 V → 5 V"))
    b.append(block(720, 100, 200, 52, "Power supply", "12 V DC · 5 A adapter"))
    b.append(block(1040, 100, 200, 52, "Fluid path", "hose 5 → head 6 → column 7", FLUID, BLUE))

    # Inputs
    b.append(block(56, 210, 230, 60, "Start / Stop button", "SW1 · momentary, on base"))
    b.append(block(56, 300, 230, 60, "Speed potentiometer", "10 kΩ · sets stroke speed"))
    b.append(block(56, 390, 230, 60, "Level sensor (3)", "float switch in the tank"))

    # Controller with pin map
    b.append(f'<rect x="380" y="210" width="220" height="350" rx="6" fill="{PART2}" stroke="{INK}" stroke-width="2.4"/>')
    b.append(t(394, 236, "Microcontroller", 14, "700"))
    b.append(t(394, 255, "Arduino Uno / Nano", 11.5, fill=MUTED))
    b.append(line(394, 268, 586, 268, INK, 0.8))
    pins = [
        ("D2 ", "←", "SW1 start / stop"),
        ("A0 ", "←", "speed pot"),
        ("D3 ", "←", "level sensor"),
        ("D4 ", "←", "LS1 top"),
        ("D5 ", "←", "LS2 bottom"),
        ("D8 ", "→", "valve driver"),
        ("D6 ", "→", "motor PWM"),
        ("D7 ", "→", "motor DIR"),
        ("D12", "→", "LED green"),
        ("D13", "→", "LED red"),
    ]
    for i, (pin, arrow, what) in enumerate(pins):
        y = 290 + i * 22
        b.append(t(394, y, f"{pin} {arrow} {what}", 11.5, family=MONO))
    b.append(t(394, 538, "runs the sequence in Fig. 3", 11.5, fill=MUTED))

    # Drivers
    b.append(block(720, 210, 200, 60, "Valve driver", "logic MOSFET + flyback diode"))
    b.append(block(720, 390, 200, 80, "Motor driver", "BTS7960 or L298N"))
    b.append(block(720, 500, 200, 54, "Status LED", "green = run · red = fault"))

    # Actuators
    b.append(block(1040, 210, 200, 60, "Solenoid valve V1 (4)", "12 V, normally closed"))
    b.append(block(1040, 390, 200, 80, "Gear motor M1", "12 V DC · inside base (9)"))

    # Mechanism row
    b.append(block(1040, 630, 200, 70, "Lead screw / belt", "turns rotation into lift", RED_T, RED))
    b.append(block(720, 630, 200, 70, "Sliding collar (8)", "strokes up and down", RED_T, RED))
    b.append(block(380, 630, 220, 70, "Limit switches", "LS1 at top · LS2 at bottom"))

    # Signal lines (inputs -> MCU)
    for y, lab in [(240, "D2"), (330, "A0"), (420, "D3")]:
        b.append(line(286, y, 378, y, INK, 1.8, "ah"))
        b.append(t(333, y - 8, lab, 11, anchor="middle", family=MONO))
    # MCU -> drivers
    b.append(line(600, 240, 718, 240, INK, 1.8, "ah"))
    b.append(t(660, 232, "D8 on/off", 11, anchor="middle"))
    b.append(line(600, 430, 718, 430, INK, 1.8, "ah"))
    b.append(t(660, 422, "D6 PWM", 11, anchor="middle"))
    b.append(t(660, 448, "D7 DIR", 11, anchor="middle"))
    b.append(line(600, 527, 718, 527, INK, 1.8, "ah"))
    b.append(t(660, 519, "D12 · D13", 11, anchor="middle"))
    # Drivers -> actuators
    b.append(line(920, 240, 1038, 240, AMBER, 2.4, "ah-amber"))
    b.append(t(1002, 262, "switched 12 V", 11, fill=AMBER, anchor="middle"))
    b.append(line(920, 430, 1038, 430, AMBER, 2.4, "ah-amber"))
    b.append(t(980, 422, "motor power", 11, fill=AMBER, anchor="middle"))

    # Power distribution
    b.append(line(720, 126, 602, 126, AMBER, 2.4, "ah-amber"))
    b.append(t(661, 118, "12 V", 11, fill=AMBER, anchor="middle"))
    b.append(line(490, 152, 490, 208, AMBER, 2.4, "ah-amber"))
    b.append(t(500, 186, "5 V", 11, fill=AMBER))
    b.append(line(820, 152, 820, 208, AMBER, 2.4, "ah-amber"))
    b.append(t(830, 186, "12 V", 11, fill=AMBER))
    # 12 V to the motor driver, hopping over the valve line
    b.append(path("M920 126 H960 V232 A8 8 0 0 1 960 248 V370 H880 V388", AMBER, 2.4, "ah-amber"))
    b.append(t(970, 330, "12 V", 11, fill=AMBER))

    # Fluid out of the valve
    b.append(line(1140, 210, 1140, 154, BLUE, 2.4, "ah-blue"))
    b.append(t(1150, 186, "fluid", 11, fill=BLUE))

    # Mechanical chain and feedback
    b.append(line(1140, 470, 1140, 628, RED, 2.6, "ah-red"))
    b.append(t(1150, 554, "rotation", 11, fill=RED))
    b.append(line(1040, 665, 922, 665, RED, 2.6, "ah-red"))
    b.append(t(981, 657, "linear motion", 11, fill=RED, anchor="middle"))
    b.append(line(720, 665, 602, 665, INK, 1.8, "ah", dash="6 4"))
    b.append(t(661, 657, "trips at ends", 11, anchor="middle"))
    b.append(line(490, 630, 490, 562, INK, 1.8, "ah"))
    b.append(t(500, 600, "D4 · D5", 11, family=MONO))

    # Legend
    lx, ly = 56, 752
    items = [
        (INK, 1.8, None, "logic signal"),
        (AMBER, 2.4, None, "power"),
        (BLUE, 2.4, None, "fluid"),
        (RED, 2.6, None, "mechanical motion"),
        (INK, 1.8, "6 4", "contact / trip"),
    ]
    x = lx
    for color, width, dash, lab in items:
        b.append(line(x, ly, x + 30, ly, color, width, dash=dash))
        b.append(t(x + 38, ly + 4, lab, 11.5))
        x += 38 + len(lab) * 7 + 28

    b.append(title_strip(960, 730, 296, "Fig. 2 · Control block diagram", 2))

    label = (
        "Block diagram: start/stop button, speed potentiometer, level sensor and two limit switches "
        "feed a microcontroller. The controller drives a valve driver that switches the 12 V solenoid "
        "valve, a motor driver that powers the gear motor, and a status LED. A 12 V supply powers the "
        "drivers and a 5 V regulator powers the controller. The motor turns a lead screw or belt that "
        "moves the sliding collar, which trips the limit switches at the stroke ends."
    )
    return svg_doc(W, H, "Fig. 2 – Control block diagram", label, defs, b)


# ---------------------------------------------------------------- Fig. 3
def fig3():
    W, H = 1280, 630
    defs = [marker("ah", INK, 11), marker("ah-red", RED, 12)]
    b = []
    b.append(t(40, 54, "Operating Sequence", 24, "700"))
    b.append(t(40, 78, "Fig. 3 — What the controller does for one run, from idle back to idle.", 13, fill=MUTED))

    y0, h = 230, 80
    cy = y0 + h / 2

    def state(x, title, l1, l2, fill=PART2, stroke=INK, title_fill=INK, offset=0):
        cx = x + 68 + offset
        return "\n".join([
            f'<rect x="{x}" y="{y0}" width="136" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>',
            t(cx, y0 + 28, title, 14, "700", title_fill, anchor="middle"),
            t(cx, y0 + 48, l1, 11.5, fill=MUTED, anchor="middle"),
            t(cx, y0 + 64, l2, 11.5, fill=MUTED, anchor="middle"),
        ])

    def diamond(cx, l1, l2=None):
        pts = f"{cx - 58},{cy} {cx},{cy - 50} {cx + 58},{cy} {cx},{cy + 50}"
        out = [f'<polygon points="{pts}" fill="{PAPER}" stroke="{INK}" stroke-width="1.8" stroke-linejoin="round"/>']
        if l2:
            out.append(t(cx, cy - 2, l1, 12.5, "700", anchor="middle"))
            out.append(t(cx, cy + 14, l2, 12.5, "700", anchor="middle"))
        else:
            out.append(t(cx, cy + 5, l1, 12.5, "700", anchor="middle"))
        return "\n".join(out)

    b.append(state(58, "Idle", "V1 closed · M1 off", "LED green"))
    b.append(diamond(294, "Level OK?"))
    b.append(state(394, "Feed", "open V1 for t_fill", "then close V1", FLUID, BLUE))
    b.append(state(572, "Stroke up", "M1 DIR = up", "until LS1 trips", offset=8))
    b.append(state(750, "Stroke down", "M1 DIR = down", "until LS2 trips", offset=8))
    b.append(diamond(986, "N cycles", "done?"))
    b.append(state(1086, "Stop", "M1 off · V1 closed", "reset counter"))
    # Direction glyphs on the stroke states
    b.append(line(588, cy + 18, 588, cy - 16, RED, 2.6, "ah-red"))
    b.append(line(766, cy - 18, 766, cy + 16, RED, 2.6, "ah-red"))

    # Fault state
    b.append(f'<rect x="226" y="420" width="136" height="70" rx="8" fill="{FAULT_T}" stroke="{FAULT}" stroke-width="1.8"/>')
    b.append(t(294, 446, "Fault", 14, "700", FAULT, anchor="middle"))
    b.append(t(294, 464, "all outputs off", 11.5, fill=MUTED, anchor="middle"))
    b.append(t(294, 480, "LED red", 11.5, fill=MUTED, anchor="middle"))

    # Forward arrows along the main row
    for x1, x2, lab in [
        (194, 234, "start"),
        (352, 392, "yes"),
        (530, 570, None),
        (708, 748, None),
        (886, 926, None),
        (1044, 1084, "yes"),
    ]:
        b.append(line(x1, cy, x2, cy, INK, 1.8, "ah"))
        if lab:
            b.append(t((x1 + x2) / 2, cy - 10, lab, 11, anchor="middle"))

    # Loop: next cycle back to Feed
    b.append(path(f"M986 {cy + 50} V380 H462 V{y0 + h + 2}", INK, 1.8, "ah"))
    b.append(t(724, 372, "no · next cycle", 11, anchor="middle"))
    # Level low -> Fault
    b.append(line(294, cy + 50, 294, 418, FAULT, 1.8, "ah"))
    b.append(t(304, 376, "no", 11, fill=FAULT))
    # Fault -> Idle
    b.append(path(f"M226 455 H126 V{y0 + h + 2}", INK, 1.8, "ah"))
    b.append(t(136, 446, "SW1 reset", 11))
    # Stop -> Idle
    b.append(path(f"M1154 {y0} V160 H126 V{y0 - 2}", INK, 1.8, "ah"))
    b.append(t(640, 152, "run complete → back to idle", 11, anchor="middle"))

    b.append(t(40, 528, "In any state: pressing SW1 goes to Stop; the level sensor reading low goes to Fault.", 12, fill=MUTED))
    b.append(t(40, 548, "t_fill, N and the stroke speed (pot on A0) are set in the firmware.", 12, fill=MUTED))

    b.append(title_strip(960, 520, 296, "Fig. 3 · Operating sequence", 3))

    label = (
        "State flow: Idle, then on start the level is checked. If low, Fault. If OK, Feed opens the "
        "valve for t_fill, then Stroke up until LS1 and Stroke down until LS2. If N cycles are not "
        "done the controller loops back to Feed; when done it goes to Stop and returns to Idle."
    )
    return svg_doc(W, H, "Fig. 3 – Operating sequence", label, defs, b)


if __name__ == "__main__":
    for name, fn in [
        ("fig1-system-layout.svg", fig1),
        ("fig2-control-block-diagram.svg", fig2),
        ("fig3-operating-sequence.svg", fig3),
    ]:
        (OUT / name).write_text(fn(), encoding="utf-8")
        print("wrote", OUT / name)
