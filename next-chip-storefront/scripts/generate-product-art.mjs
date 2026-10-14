#!/usr/bin/env node
// Generates the DEMO product renders in public/images/products from
// src/data/demo/products.json. These are stylized illustrations for the demo
// catalog (no photography or third-party assets). Run: npm run art
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const products = JSON.parse(readFileSync(join(root, "src/data/demo/products.json"), "utf8"));
const out = join(root, "public/images/products");
mkdirSync(out, { recursive: true });

const shade = (hex, amt) => {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(v + amt * 255))));
  return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
};
const isLight = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return ((n >> 16) & 255) * 0.3 + ((n >> 8) & 255) * 0.59 + (n & 255) * 0.11 > 150;
};

function defs(id, body, accent) {
  return `<defs>
  <radialGradient id="bg${id}" cx="50%" cy="42%" r="70%"><stop offset="0" stop-color="#1b1f25"/><stop offset="1" stop-color="#0a0b0d"/></radialGradient>
  <linearGradient id="body${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${shade(body, 0.1)}"/><stop offset="0.55" stop-color="${body}"/><stop offset="1" stop-color="${shade(body, -0.12)}"/></linearGradient>
  <linearGradient id="sheen${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="acc${id}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${accent}"/><stop offset="1" stop-color="${shade(accent, -0.18)}"/></linearGradient>
  <pattern id="grid${id}" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#ffffff" stroke-opacity=".035"/></pattern>
  <filter id="shadow${id}" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#000" flood-opacity=".55"/></filter>
</defs>`;
}

const edge = (body) => (isLight(body) ? "#9aa3ad" : "#3a4048");

// ---- Product shapes (drawn around a 800×800 canvas centre) -------------------------
function mouse({ style, body, accent }, id) {
  const shapes = {
    sym: "M400 160C505 160 548 262 548 382C548 524 506 646 400 646C294 646 252 524 252 382C252 262 295 160 400 160Z",
    ergo: "M378 160C505 152 566 252 556 404C547 546 486 648 390 648C296 648 246 566 250 432C254 300 286 166 378 160Z",
    honey: "M400 160C505 160 548 262 548 382C548 524 506 646 400 646C294 646 252 524 252 382C252 262 295 160 400 160Z",
    mini: "M400 200C490 200 526 284 526 386C526 508 490 612 400 612C310 612 274 508 274 386C274 284 310 200 400 200Z",
    sleek: "M400 160C505 160 548 262 548 382C548 524 506 646 400 646C294 646 252 524 252 382C252 262 295 160 400 160Z",
  };
  const d = shapes[style] ?? shapes.sym;
  const top = style === "mini" ? 205 : 165;
  let holes = "";
  if (style === "honey") {
    for (let y = 400; y < 620; y += 34)
      for (let x = 300 + ((y / 34) % 2) * 17; x < 510; x += 34)
        holes += `<path d="M${x} ${y - 11}l10 6v11l-10 6l-10-6v-11z" fill="#0b0c0e" opacity=".85"/>`;
    holes = `<g clip-path="url(#clip${id})">${holes}</g>`;
  }
  const side = style === "ergo" ? `<rect x="243" y="350" width="14" height="44" rx="6" fill="${shade(body, -0.2)}" stroke="${edge(body)}"/><rect x="243" y="404" width="14" height="40" rx="6" fill="${shade(body, -0.2)}" stroke="${edge(body)}"/>` : "";
  return `<clipPath id="clip${id}"><path d="${d}"/></clipPath>
  <g filter="url(#shadow${id})">${side}
    <path d="${d}" fill="url(#body${id})" stroke="${edge(body)}" stroke-width="2"/>
    ${holes}
    <path d="M400 ${top + 6}V352" stroke="${shade(body, -0.25)}" stroke-width="3"/>
    <path d="M${style === "mini" ? 284 : 262} 352C330 372 470 372 ${style === "mini" ? 516 : 538} 352" fill="none" stroke="${shade(body, -0.25)}" stroke-width="3"/>
    <rect x="390" y="${top + 52}" width="20" height="56" rx="10" fill="#0d0f12" stroke="${accent}" stroke-width="2"/>
    <rect x="396" y="${top + 62}" width="8" height="36" rx="4" fill="url(#acc${id})"/>
    <path d="${d}" fill="url(#sheen${id})"/>
    <g transform="translate(400 ${style === "mini" ? 540 : 566})"><rect x="-13" y="-13" width="26" height="26" rx="5" fill="none" stroke="${accent}" stroke-width="2.5"/><rect x="-5" y="-5" width="10" height="10" rx="2" fill="${accent}"/></g>
  </g>`;
}

function mousepad({ style, accent }, id) {
  const pad = "M190 290Q200 270 222 270H578Q600 270 610 290L702 520Q712 548 684 548H116Q88 548 98 520Z";
  let tex = "";
  if (style === "glass") {
    tex = `<path d="M260 270L180 548M420 270L340 548M560 270L480 548" stroke="#fff" stroke-opacity=".08" stroke-width="26"/>
      <path d="${pad}" fill="${accent}" opacity=".06"/>`;
  } else if (style === "topo") {
    for (let i = 0; i < 9; i++)
      tex += `<path d="M${120 + i * 12} ${520 - i * 26}C${260} ${470 - i * 30} ${380} ${560 - i * 34} ${560} ${470 - i * 24}S${680} ${440 - i * 22} ${690} ${420 - i * 20}" fill="none" stroke="${accent}" stroke-opacity="${0.12 + i * 0.03}" stroke-width="2"/>`;
  } else {
    for (let x = 0; x < 640; x += 6) tex += `<path d="M${120 + x} 548L${200 + x * 0.94} 270" stroke="#fff" stroke-opacity=".05"/>`;
  }
  return `<clipPath id="clip${id}"><path d="${pad}"/></clipPath>
  <g filter="url(#shadow${id})">
    <path d="M98 520L98 534Q98 562 126 562H674Q702 562 702 534L702 520" fill="#060708"/>
    <path d="${pad}" fill="${style === "glass" ? "#1a1f26" : "#20242b"}"/>
    <path d="${pad}" fill="url(#sheen${id})" opacity=".6"/>
    <g clip-path="url(#clip${id})">${tex}</g>
    <path d="${pad}" fill="none" stroke="${accent}" stroke-width="3" stroke-dasharray="${style === "glass" ? "0" : "7 6"}" opacity=".9"/>
    <g transform="translate(616 512)"><rect x="-11" y="-11" width="22" height="22" rx="4" fill="none" stroke="${accent}" stroke-width="2"/><rect x="-4" y="-4" width="8" height="8" rx="1.5" fill="${accent}"/></g>
  </g>`;
}

function skates({ style, body, accent }, id) {
  let parts = "";
  const fill = style === "glass" ? accent : "#f1f3f5";
  const op = style === "glass" ? 0.35 : 1;
  if (style === "dots") {
    for (let r = 0; r < 4; r++)
      for (let c = 0; c < 5; c++)
        parts += `<circle cx="${250 + c * 75}" cy="${270 + r * 75}" r="24" fill="${fill}" stroke="#c9d0d6" stroke-width="2"/><circle cx="${244 + c * 75}" cy="${263 + r * 75}" r="7" fill="#fff" opacity=".6"/>`;
  } else if (style === "glass") {
    parts = [
      "M250 280h120q20 0 20 20v20q0 20-20 20h-120q-20 0-20-20v-20q0-20 20-20z",
      "M430 280h120q20 0 20 20v20q0 20-20 20h-120q-20 0-20-20v-20q0-20 20-20z",
      "M260 430c40-20 80-20 120 0v60c-40 20-80 20-120 0z",
      "M420 430c40-20 80-20 120 0v60c-40 20-80 20-120 0z",
    ]
      .map((d) => `<path d="${d}" fill="${fill}" fill-opacity="${op}" stroke="${accent}" stroke-width="3"/><path d="${d}" fill="url(#sheen${id})"/>`)
      .join("");
  } else {
    parts = `<path d="M240 270q160-50 320 0l-20 60q-140-36-280 0z" fill="${fill}" stroke="#c9d0d6" stroke-width="2"/>
      <path d="M260 470q140 40 280 0l20 60q-160 50-320 0z" fill="${fill}" stroke="#c9d0d6" stroke-width="2"/>
      <rect x="250" y="370" width="80" height="44" rx="22" fill="${fill}" stroke="#c9d0d6" stroke-width="2"/>
      <rect x="470" y="370" width="80" height="44" rx="22" fill="${fill}" stroke="#c9d0d6" stroke-width="2"/>`;
  }
  return `<g filter="url(#shadow${id})">
    <rect x="190" y="200" width="420" height="400" rx="28" fill="${shade(body === "#17191d" ? "#1d2127" : body, -0.02)}" stroke="#2a2f36" stroke-width="2"/>
    <rect x="190" y="200" width="420" height="34" rx="17" fill="${accent}" opacity=".9"/>
    ${parts}
  </g>`;
}

function keyboard({ style, body, accent }, id) {
  const cols = { 60: 14, 65: 15, 75: 15, tkl: 17 }[style] ?? 15;
  const rows = style === "60" || style === "65" ? 5 : 6;
  const k = cols > 15 ? 29 : 32, gap = 6; // wide layouts get smaller keys so they stay in frame
  const w = cols * (k + gap) + 30, h = rows * (k + gap) + 34;
  const x0 = 400 - w / 2, y0 = 400 - h / 2;
  let keys = "";
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      if (style === "75" && r === 0 && c === cols - 1) continue;
      const accentKey = (r === 0 && c === 0) || (r === rows - 2 && c === cols - 2);
      keys += `<rect x="${x0 + 15 + c * (k + gap)}" y="${y0 + 17 + r * (k + gap)}" width="${k}" height="${k}" rx="7" fill="${accentKey ? accent : shade(body, 0.06)}" stroke="${shade(body, -0.1)}"/>
        <rect x="${x0 + 19 + c * (k + gap)}" y="${y0 + 19 + r * (k + gap)}" width="${k - 8}" height="${k - 12}" rx="5" fill="#fff" opacity="${accentKey ? 0.18 : 0.05}"/>`;
    }
  const space = `<rect x="${x0 + 15 + 4 * (k + gap)}" y="${y0 + 17 + (rows - 1) * (k + gap)}" width="${6 * (k + gap) - gap}" height="${k}" rx="7" fill="${shade(body, 0.08)}" stroke="${shade(body, -0.1)}"/>`;
  const knob = style === "75" ? `<circle cx="${x0 + 15 + (cols - 1) * (k + gap) + k / 2}" cy="${y0 + 17 + k / 2}" r="17" fill="#0d0f12" stroke="${accent}" stroke-width="3"/>` : "";
  return `<g filter="url(#shadow${id})" transform="rotate(-6 400 400)">
    <rect x="${x0}" y="${y0}" width="${w}" height="${h}" rx="22" fill="url(#body${id})" stroke="${edge(body)}" stroke-width="2"/>
    ${keys}${space}${knob}
    <rect x="${x0}" y="${y0}" width="${w}" height="${h}" rx="22" fill="url(#sheen${id})"/>
    <rect x="${x0 + w / 2 - 40}" y="${y0 - 8}" width="80" height="10" rx="5" fill="${accent}" opacity=".85"/>
  </g>`;
}

function headset({ style, body, accent }, id) {
  const grill = style === "studio" ? Array.from({ length: 5 }, (_, i) => `<circle cx="0" cy="0" r="${18 + i * 14}" fill="none" stroke="#0b0c0e" stroke-opacity=".5" stroke-width="5"/>`).join("") : "";
  const cup = (x, flip) => `<g transform="translate(${x} 470)${flip ? " scale(-1 1)" : ""}">
      <rect x="-70" y="-110" width="140" height="220" rx="66" fill="url(#body${id})" stroke="${edge(body)}" stroke-width="2"/>
      ${grill}
      <rect x="-48" y="-82" width="96" height="164" rx="46" fill="none" stroke="${accent}" stroke-width="3" opacity=".9"/>
      <rect x="-70" y="-110" width="140" height="220" rx="66" fill="url(#sheen${id})"/>
    </g>`;
  const mic = style === "wireless" ? `<path d="M232 560C220 640 300 680 370 664" fill="none" stroke="${shade(body, -0.05)}" stroke-width="12" stroke-linecap="round"/><circle cx="378" cy="662" r="15" fill="${accent}"/>` : "";
  return `<g filter="url(#shadow${id})">
    <path d="M232 450C232 250 312 168 400 168S568 250 568 450" fill="none" stroke="${shade(body, -0.08)}" stroke-width="34" stroke-linecap="round"/>
    <path d="M250 440C250 270 320 198 400 198S550 270 550 440" fill="none" stroke="${accent}" stroke-opacity=".35" stroke-width="6"/>
    ${mic}${cup(232, false)}${cup(568, true)}
  </g>`;
}

function iem({ style, accent }, id) {
  const shell = (x, flip) => `<g transform="translate(${x} 380)${flip ? " scale(-1 1)" : ""}">
      <path d="M-70 -40C-70 -110 40 -120 70 -60C96 -6 64 70 0 78C-50 84 -70 30 -70 -40Z" fill="${style === "dual" ? "#1f2229" : "#15171b"}" stroke="#3a4048" stroke-width="2"/>
      <path d="M-46 -44C-46 -86 26 -92 46 -54C60 -24 44 26 2 32C-30 36 -46 4 -46 -44Z" fill="url(#acc${id})" opacity="${style === "dual" ? 0.85 : 0.55}"/>
      <rect x="44" y="-12" width="44" height="26" rx="12" fill="#2b3038" transform="rotate(24 44 0)"/>
      <path d="M-46 -44C-46 -86 26 -92 46 -54" fill="none" stroke="#fff" stroke-opacity=".3" stroke-width="4"/>
    </g>`;
  return `<g filter="url(#shadow${id})">
    <path d="M300 440C300 560 360 600 400 640C440 600 500 560 500 440" fill="none" stroke="#2f343c" stroke-width="7"/>
    <path d="M400 640V700" stroke="#2f343c" stroke-width="7"/><rect x="386" y="700" width="28" height="44" rx="6" fill="#20242a" stroke="${accent}" stroke-width="2"/>
    ${shell(300, false)}${shell(500, true)}
  </g>`;
}

function microphone({ style, body, accent }, id) {
  if (style === "arm") {
    return `<g filter="url(#shadow${id})" stroke-linecap="round">
      <rect x="180" y="610" width="90" height="40" rx="8" fill="#20242a" stroke="#3a4048"/>
      <path d="M225 610L300 420L520 300" fill="none" stroke="${shade(body, -0.35)}" stroke-width="22"/>
      <path d="M225 610L300 420L520 300" fill="none" stroke="${accent}" stroke-width="4" stroke-opacity=".7"/>
      <circle cx="300" cy="420" r="20" fill="#0d0f12" stroke="${accent}" stroke-width="4"/>
      <rect x="505" y="285" width="70" height="30" rx="10" fill="#20242a" stroke="${accent}" stroke-width="2"/>
    </g>`;
  }
  const tall = style === "xlr";
  const h = tall ? 330 : 260, w = tall ? 120 : 140;
  const x = 400 - w / 2, y = tall ? 170 : 200;
  let slots = "";
  for (let i = 0; i < 8; i++) slots += `<rect x="${x + 18}" y="${y + 22 + i * 16}" width="${w - 36}" height="6" rx="3" fill="#0b0c0e" opacity=".75"/>`;
  return `<g filter="url(#shadow${id})">
    <path d="M${x - 36} ${y + h - 60}V${y + h + 40}M${x + w + 36} ${y + h - 60}V${y + h + 40}" stroke="#2f343c" stroke-width="12" stroke-linecap="round"/>
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${w / 2}" fill="url(#body${id})" stroke="${edge(body)}" stroke-width="2"/>
    ${slots}
    <rect x="${x}" y="${y + h - 110}" width="${w}" height="10" fill="${accent}"/>
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${w / 2}" fill="url(#sheen${id})"/>
    <path d="M${x - 36} ${y + h + 40}H${x + w + 36}" stroke="#2f343c" stroke-width="12" stroke-linecap="round"/>
    <rect x="${400 - 70}" y="${y + h + 60}" width="140" height="26" rx="13" fill="#1d2127" stroke="#2f343c"/>
  </g>`;
}

function cable({ style, accent }, id) {
  if (style === "bungee") {
    return `<g filter="url(#shadow${id})">
      <ellipse cx="400" cy="600" rx="140" ry="44" fill="#1d2127" stroke="#3a4048" stroke-width="2"/>
      <path d="M400 590V430" stroke="#2f343c" stroke-width="16"/>
      <path d="M400 430C420 330 470 280 560 250" fill="none" stroke="${accent}" stroke-width="10" stroke-linecap="round"/>
      <circle cx="560" cy="250" r="22" fill="#0d0f12" stroke="${accent}" stroke-width="5"/>
      <path d="M200 300C300 220 480 240 560 250" fill="none" stroke="#3a4048" stroke-width="7" stroke-dasharray="3 6"/>
    </g>`;
  }
  if (style === "grip") {
    return `<g filter="url(#shadow${id})">
      ${[[230, 240, -8], [420, 230, 6], [260, 450, 4], [450, 440, -5]]
        .map(([x, y, r]) => `<g transform="rotate(${r} ${x + 60} ${y + 80})"><path d="M${x} ${y + 20}Q${x} ${y} ${x + 20} ${y}H${x + 110}Q${x + 130} ${y} ${x + 128} ${y + 30}L${x + 118} ${y + 150}Q${x + 116} ${y + 170} ${x + 96} ${y + 170}H${x + 18}Q${x} ${y + 170} ${x} ${y + 150}Z" fill="#1b1e23" stroke="${accent}" stroke-width="2.5"/>${Array.from({ length: 24 }, (_, i) => `<circle cx="${x + 22 + (i % 4) * 28}" cy="${y + 24 + Math.floor(i / 4) * 24}" r="3" fill="#fff" opacity=".12"/>`).join("")}</g>`)
        .join("")}
    </g>`;
  }
  const coil = style === "coiled" ? Array.from({ length: 12 }, (_, i) => `<ellipse cx="${300 + i * 18}" cy="400" rx="16" ry="44" fill="none" stroke="${accent}" stroke-width="7"/>`).join("") : "";
  const path = style === "coiled" ? "M160 520C200 420 260 400 290 400M510 400C560 400 600 360 640 280" : "M150 560C220 340 330 640 420 420S600 220 650 300";
  return `<g filter="url(#shadow${id})" stroke-linecap="round">
    <path d="${path}" fill="none" stroke="#2c3138" stroke-width="16"/>
    <path d="${path}" fill="none" stroke="${accent}" stroke-width="16" stroke-dasharray="2 9" opacity=".85"/>
    ${coil}
    <rect x="${style === "coiled" ? 128 : 118}" y="${style === "coiled" ? 520 : 556}" width="64" height="40" rx="8" fill="#20242a" stroke="${accent}" stroke-width="2" transform="rotate(-62 ${style === "coiled" ? 160 : 150} ${style === "coiled" ? 540 : 576})"/>
    <rect x="${style === "coiled" ? 618 : 628}" y="${style === "coiled" ? 250 : 270}" width="54" height="34" rx="10" fill="#20242a" stroke="${accent}" stroke-width="2" transform="rotate(-50 ${style === "coiled" ? 645 : 655} ${style === "coiled" ? 267 : 287})"/>
    ${style === "coiled" ? `<circle cx="300" cy="400" r="26" fill="#14171b" stroke="#3a4048" stroke-width="4"/>` : ""}
  </g>`;
}

const DRAW = { mouse, mousepad, skates, keyboard, headset, iem, microphone, cable };

function render(product, view) {
  const id = `${product.slug.replace(/[^a-z0-9]/g, "")}${view}`;
  const art = product.art;
  const shape = DRAW[art.kind](art, id);
  const transforms = [
    "translate(-40 -40) scale(1.1)",
    "rotate(-14 400 400) translate(10 6) scale(.94)",
    "translate(-400 -400) scale(2)",
  ];
  const glow = view === 1 ? art.accent : view === 2 ? shade(art.accent, -0.2) : "#ffffff";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" width="800" height="800" role="img" aria-label="${product.name} (demo render)">
${defs(id, art.body, art.accent)}
<rect width="800" height="800" fill="url(#bg${id})"/>
<rect width="800" height="800" fill="url(#grid${id})"/>
<ellipse cx="400" cy="700" rx="${view === 3 ? 0 : 250}" ry="26" fill="${glow}" opacity=".08"/>
<g transform="${view === 3 ? "translate(-300 -260) scale(1.75)" : transforms[view - 1]}">${shape}</g>
<text x="772" y="776" text-anchor="end" font-family="Arial, sans-serif" font-size="13" letter-spacing="2" fill="#ffffff" fill-opacity=".28">DEMO RENDER</text>
</svg>`;
}

let count = 0;
for (const p of products) {
  for (const view of [1, 2, 3]) {
    writeFileSync(join(out, `${p.slug}-${view}.svg`), render(p, view));
    count++;
  }
}

writeFileSync(
  join(root, "public/images/placeholder.svg"),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" width="800" height="800" role="img" aria-label="Image unavailable">
<rect width="800" height="800" fill="#121417"/>
<g fill="none" stroke="#3a4048" stroke-width="10" stroke-linejoin="round"><rect x="290" y="290" width="220" height="220" rx="28"/><rect x="350" y="350" width="100" height="100" rx="12"/>
<path d="M350 290v-50M400 290v-50M450 290v-50M350 560v-50M400 560v-50M450 560v-50M290 350h-50M290 400h-50M290 450h-50M560 350h-50M560 400h-50M560 450h-50"/></g>
</svg>`,
);
console.log(`Wrote ${count} demo renders and placeholder.svg`);
