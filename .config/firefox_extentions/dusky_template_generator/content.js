/*
 * Dusky Template Generator — content.js (Production Fixed Edition)
 * Gecko 156+ only. Zero legacy fallbacks.
 */
"use strict";
(() => {
  if (globalThis.__duskyTemplateGenerator) return;
  globalThis.__duskyTemplateGenerator = true;

  /* ── Material 3 palette contract ─────────────────────────────────────── */
  const TOKENS = [
    ["background", "Background (Page canvas)"],
    ["on_background", "On background"],
    ["surface", "Surface (Base)"],
    ["surface_container_lowest", "Surface container lowest"],
    ["surface_container_low", "Surface container low"],
    ["surface_container", "Surface container (Cards)"],
    ["surface_container_high", "Surface container high (Modals)"],
    ["surface_container_highest", "Surface container highest"],
    ["surface_bright", "Surface bright"],
    ["surface_dim", "Surface dim"],
    ["surface_variant", "Surface variant"],
    ["on_surface", "On surface (Main text)"],
    ["on_surface_variant", "On surface variant (Muted)"],
    ["inverse_surface", "Inverse surface"],
    ["inverse_on_surface", "Inverse on surface"],
    ["primary", "Primary (Brand accent)"],
    ["on_primary", "On primary"],
    ["primary_container", "Primary container"],
    ["on_primary_container", "On primary container"],
    ["primary_fixed", "Primary fixed (Hover)"],
    ["primary_fixed_dim", "Primary fixed dim (Active)"],
    ["secondary", "Secondary"],
    ["on_secondary", "On secondary"],
    ["secondary_container", "Secondary container"],
    ["on_secondary_container", "On secondary container"],
    ["secondary_fixed_dim", "Secondary fixed dim"],
    ["on_secondary_fixed_variant", "On secondary fixed variant"],
    ["tertiary", "Tertiary"],
    ["on_tertiary", "On tertiary"],
    ["tertiary_container", "Tertiary container"],
    ["on_tertiary_container", "On tertiary container"],
    ["outline", "Outline (Borders)"],
    ["outline_variant", "Outline variant (Dividers)"],
    ["error", "Error"],
    ["on_error", "On error"],
    ["error_container", "Error container"],
  ];
  const TOKEN_NAMES = new Set(TOKENS.map(([t]) => t));
  const OWNED = new Set([...TOKEN_NAMES].map((t) => "--" + t));
  const NOISE_RE = /^--(tw|fa|dusky|darkreader|wp--|chakra-emotion|mui-)/i;
  const skipVar = (name) => OWNED.has(name) || NOISE_RE.test(name);

  const paletteLoaded = () =>
    getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() !== "";

  /* ── Perceptual colour engine (Color Guard Fixed) ────────────────────── */
  let colorProbe = null;
  function getProbe() {
    if (!colorProbe || !colorProbe.isConnected) {
      colorProbe = document.createElement("span");
      colorProbe.style.cssText =
        "display:none !important;position:fixed !important;visibility:hidden !important;";
      (document.head || document.documentElement).append(colorProbe);
    }
    return colorProbe;
  }
  function dropProbe() {
    colorProbe?.remove();
    colorProbe = null;
  }

  const RGB_OUT = /^(?:rgb|rgba)\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.%]+))?\s*\)$/i;
  const IS_COLOR_SYNTAX = /^(#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark)\()/i;
  const HSL_TRIPLET = /^(-?[\d.]+)(?:deg)?\s+([\d.]+)%\s+([\d.]+)%$/;
  const RGB_TRIPLET = /^(\d{1,3})[,\s]+(\d{1,3})[,\s]+(\d{1,3})$/;

  function parseCssColor(raw) {
    if (typeof raw !== "string") return null;
    const v = raw.trim();
    if (!v) return null;
    if (/^(inherit|initial|unset|revert|revert-layer|transparent|currentcolor|none)$/i.test(v)) return null;

    const hsl = v.match(HSL_TRIPLET);
    const rgbTriplet = !hsl && v.match(RGB_TRIPLET);

    if (rgbTriplet) {
      const [, r, g, b] = rgbTriplet.map(Number);
      if (r <= 255 && g <= 255 && b <= 255) return { r, g, b, a: 1, shape: "rgb-triplet" };
      return null;
    }

    /* Guard: Reject non-colors immediately so font/spacing variables never leak through */
    const isLikelyColor = hsl || IS_COLOR_SYNTAX.test(v) || CSS.supports("color", v);
    if (!isLikelyColor) return null;

    const probe = getProbe();
    probe.style.color = "";
    probe.style.color = hsl ? `hsl(${v})` : v;

    /* If the browser rejected the property, probe.style.color remains empty */
    if (!probe.style.color) return null;

    const comp = getComputedStyle(probe).color;
    const match = comp && RGB_OUT.exec(comp);
    if (!match) return null;
    const [, rStr, gStr, bStr, aStr] = match;
    const alpha = aStr === undefined ? 1 : (aStr.endsWith("%") ? parseFloat(aStr) / 100 : parseFloat(aStr));
    return {
      r: Math.round(+rStr),
      g: Math.round(+gStr),
      b: Math.round(+bStr),
      a: alpha,
      shape: hsl ? "hsl-triplet" : "color",
    };
  }

  const srgb = (c) => (c /= 255, c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = (r, g, b) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);

  function chromaHue(r, g, b) {
    const rf = r / 255, gf = g / 255, bf = b / 255;
    const max = Math.max(rf, gf, bf), min = Math.min(rf, gf, bf), d = max - min;
    let h = 0;
    if (d !== 0) {
      if (max === rf) h = ((gf - bf) / d) % 6;
      else if (max === gf) h = (bf - rf) / d + 2;
      else h = (rf - gf) / d + 4;
      h = Math.round(h * 60);
      if (h < 0) h += 360;
    }
    return { chroma: d, hue: h };
  }

  /* ── Framework signature table ───────────────────────────────────────── */
  function matchKnownFramework(name) {
    const n = name.toLowerCase();

    /* YouTube / Polymer */
    if (n.startsWith("--yt-")) {
      if (n.includes("base-background") || n.includes("general-background-a")) return "background";
      if (n.includes("raised-background") || n.includes("menu-background")) return "surface_container";
      if (n.includes("general-background-b")) return "surface_container_low";
      if (n.includes("general-background-c")) return "surface_container_lowest";
      if (n.includes("text-primary")) return "on_surface";
      if (n.includes("text-secondary")) return "on_surface_variant";
      if (n.includes("icon-inactive")) return "outline";
      if (n.includes("icon-color") || n.includes("icon-active")) return "on_surface";
      if (n.includes("brand-background-solid") || n.includes("call-to-action") ||
          n.includes("static-brand-red") || n.includes("red-indicator") ||
          n.includes("brand-icon-active")) return "primary";
      if (n.includes("badge-chip-background")) return "surface_container_high";
      if (n.includes("button-chip-background-hover")) return "surface_bright";
      if (n.includes("10-percent-layer")) return "surface_variant";
    }

    /* Google Material / Gemini */
    if (n.startsWith("--gem-sys-color--") || n.startsWith("--mat-") || n.startsWith("--bard-color-")) {
      const tail = n.replace(/^--(gem-sys-color--|mat-|bard-color-)/, "");
      const map = {
        "primary": "primary", "on-primary": "on_primary",
        "primary-container": "primary_container", "on-primary-container": "on_primary_container",
        "secondary": "secondary", "on-secondary": "on_secondary",
        "secondary-container": "secondary_container", "on-secondary-container": "on_secondary_container",
        "tertiary": "tertiary", "on-tertiary": "on_tertiary",
        "surface": "surface", "surface-bright": "surface_bright", "surface-dim": "surface_dim",
        "surface-container": "surface_container", "surface-container-high": "surface_container_high",
        "surface-container-highest": "surface_container_highest",
        "surface-container-low": "surface_container_low",
        "surface-container-lowest": "surface_container_lowest",
        "on-surface": "on_surface", "on-surface-variant": "on_surface_variant",
        "outline": "outline", "outline-variant": "outline_variant",
        "error": "error", "on-error": "on_error",
      };
      if (map[tail]) return map[tail];
      if (tail.includes("app-text-color")) return "on_surface";
      if (tail.includes("background-color")) return "surface";
    }

    /* Tailwind v4 / shadcn / Radix */
    const shadcn = {
      "--background": "background", "--foreground": "on_background",
      "--card": "surface_container", "--card-foreground": "on_surface",
      "--popover": "surface_container_high", "--popover-foreground": "on_surface",
      "--primary": "primary", "--primary-foreground": "on_primary",
      "--secondary": "secondary_container", "--secondary-foreground": "on_secondary_container",
      "--muted": "surface_container_low", "--muted-foreground": "on_surface_variant",
      "--accent": "surface_container_high", "--accent-foreground": "on_surface",
      "--destructive": "error", "--destructive-foreground": "on_error",
      "--border": "outline_variant", "--input": "outline", "--ring": "primary",
      "--sidebar": "surface_container", "--sidebar-foreground": "on_surface",
      "--sidebar-primary": "primary", "--sidebar-accent": "surface_container_high",
      "--sidebar-border": "outline_variant", "--sidebar-ring": "primary",
    };
    if (shadcn[n]) return shadcn[n];

    /* Discord */
    if (n.startsWith("--neutral-")) {
      const num = Number.parseInt(n.slice(10), 10);
      if (Number.isFinite(num)) {
        if (num >= 90) return "surface";
        if (num >= 84) return "surface_container_low";
        if (num >= 78) return "surface_container";
        if (num >= 70) return "surface_container_high";
        if (num <= 10) return "on_surface";
        if (num <= 30) return "on_surface_variant";
      }
    }
    if (n.startsWith("--blurple-") || n.startsWith("--brand-") || n === "--blue-new-37") {
      if (n === "--brand-560") return "on_primary_container";
      if (n === "--brand-10a" || n.includes("highlight")) return "inverse_on_surface";
      if (n.includes("60")) return "secondary_container";
      if (n.includes("50") || n.includes("65")) return "primary_container";
      return "primary";
    }

    /* Instagram */
    if (n.startsWith("--ig-")) {
      if (n.includes("primary-background")) return "surface";
      if (n.includes("primary-text") || n.includes("primary-icon")) return "on_surface";
      if (n.includes("elevated-background")) return "surface_container_low";
      if (n.includes("separator")) return "outline_variant";
    }

    /* Chess.com */
    if (n.startsWith("--color-gray-") || n.startsWith("--color-green-")) {
      if (n.includes("gray-800")) return "surface";
      if (n.includes("gray-700")) return "surface_container";
      if (n.includes("gray-600")) return "surface_container_high";
      if (n.includes("gray-500")) return "surface_container_highest";
      if (n.includes("gray-400")) return "surface_bright";
      if (n.includes("green-300")) return "primary";
      if (n.includes("green-200")) return "primary_fixed";
      if (n.includes("green-400") || n.includes("green-500")) return "primary_container";
    }
    if (n.includes("neutrals-white")) return "on_surface";

    /* Telegram */
    if (n.startsWith("--theme-") || n.startsWith("--color-")) {
      if (n.includes("chat-hover") || n.includes("background-selected")) return "surface_container_high";
      if (n.includes("chat-active") || n.includes("background-own")) return "primary_container";
      if (n.includes("background-secondary")) return "surface_container_lowest";
      if (n.includes("background-compact-menu") || n.includes("action-message-bg")) return "surface_container_low";
      if (n.includes("theme-background-color") || n === "--color-background") return "surface";
      if (n.includes("color-text")) return "on_surface_variant";
    }

    /* Monkeytype */
    if (n === "--bg-color") return "surface";
    if (n === "--main-color" || n === "--text-color") return "primary";
    if (n === "--caret-color") return "primary_fixed";
    if (n === "--sub-color") return "primary_container";
    if (n === "--sub-alt-color") return "surface_container_low";

    return "";
  }

  function classifyByValueAndName(name, col) {
    const n = name.slice(2).toLowerCase().replaceAll(/[_.]/g, "-");
    const lum = luminance(col.r, col.g, col.b);
    const { chroma, hue } = chromaHue(col.r, col.g, col.b);

    if (/(error|danger|destructive|critical|invalid)/.test(n)) return "error";
    if (/(border|divider|separator|rule|stroke)/.test(n)) return lum > 0.3 ? "outline" : "outline_variant";
    if (/outline/.test(n)) return "outline";
    if (/(link|primary|brand|accent|cta)/.test(n) && chroma >= 0.1) return "primary";

    if (chroma >= 0.15) {
      if (hue >= 340 || hue <= 25) return /(btn|action|brand|primary)/.test(n) ? "primary" : "error";
      if (hue <= 65) return "tertiary";
      if (hue <= 170) return "secondary";
      if (hue <= 280) return "primary";
      return "tertiary";
    }

    if (lum <= 0.02) {
      if (/(body|canvas|bg-base|root|background|black)/.test(n)) return "background";
      return "surface_container_lowest";
    }
    if (lum <= 0.06) {
      if (/(input|field|inset|sunken|deep)/.test(n)) return "surface_container_low";
      return "surface";
    }
    if (lum <= 0.12) {
      if (/(card|panel|box|container|sidebar|nav)/.test(n)) return "surface_container";
      return "surface_container_low";
    }
    if (lum <= 0.22) {
      if (/(modal|dialog|popover|dropdown|menu|toast|elevated)/.test(n)) return "surface_container_high";
      return "surface_container";
    }
    if (lum <= 0.38) {
      if (/(hover|active|bright)/.test(n)) return "surface_bright";
      return "surface_container_highest";
    }
    if (lum >= 0.70) {
      if (/(muted|secondary|dim|subtle|caption|hint|disabled|placeholder)/.test(n)) return "on_surface_variant";
      return "on_surface";
    }
    return "on_surface_variant";
  }

  /* ── Stylesheet traversal ────────────────────────────────────────────── */
  function walkRules(list, onStyleRule) {
    for (const rule of list) {
      if (rule.styleSheet) {
        try { walkRules(rule.styleSheet.cssRules, onStyleRule); } catch { /* cross-origin */ }
        continue;
      }
      if (rule.cssRules) {
        try { walkRules(rule.cssRules, onStyleRule); } catch { /* opaque */ }
      }
      if (rule.selectorText && rule.style) onStyleRule(rule);
    }
  }

  let customPropIndex = null;
  function buildCustomPropIndex() {
    const index = [];
    for (const sheet of document.styleSheets) {
      try {
        walkRules(sheet.cssRules, (rule) => {
          const props = [];
          for (const p of rule.style) if (p.startsWith("--")) props.push(p);
          if (props.length) index.push({ sel: rule.selectorText, props });
        });
      } catch { /* cross-origin */ }
    }
    return index;
  }
  const propIndex = () => (customPropIndex ??= buildCustomPropIndex());

  function detectRootScopes() {
    const inner = new Set();
    for (const el of [document.documentElement, document.body].filter(Boolean)) {
      for (const cls of el.classList) {
        if (/^(dark|dark-theme|theme-dark|dark-mode|night)$/i.test(cls)) inner.add("." + CSS.escape(cls));
      }
      for (const attr of el.getAttributeNames()) {
        if (/^(data-theme|data-color-mode|data-bs-theme|theme|dark)$/i.test(attr)) {
          const val = el.getAttribute(attr);
          inner.add(val ? `[${attr}="${CSS.escape(val)}"]` : `[${attr}]`);
        }
      }
    }
    inner.add("[dark]");
    inner.add(".dark");
    inner.add('[data-theme="dark"]');
    return `:root, :where(${[...inner].join(", ")})`;
  }

  function collectVariables() {
    const names = new Set();
    const rootCs = getComputedStyle(document.documentElement);
    const bodyCs = document.body ? getComputedStyle(document.body) : rootCs;
    for (const cs of new Set([rootCs, bodyCs])) {
      for (const p of cs) if (p.startsWith("--")) names.add(p);
    }
    const rootish = /(^|,)\s*(?::root|html|body|\[dark\]|\.dark|\[data-theme)/i;
    for (const { sel, props } of propIndex()) {
      if (rootish.test(sel)) for (const p of props) names.add(p);
    }
    const out = new Map();
    for (const n of names) {
      const v = (rootCs.getPropertyValue(n) || bodyCs.getPropertyValue(n)).trim();
      if (v) out.set(n, v);
    }
    return out;
  }

  function structuralFallback() {
    return [
      "/* Structural theme — this page exposes no usable design tokens. */",
      "html, body {",
      "    background-color: var(--surface) !important;",
      "    color: var(--on_surface) !important;",
      "    color-scheme: dark !important;",
      "    scrollbar-color: var(--surface_variant) transparent !important;",
      "}",
      "",
      ":not(a):not(button):not(input):not(select):not(textarea):not(code):not(pre):not(kbd)" +
        ":not(table):not(thead):not(tbody):not(tr):not(th):not(td):not(svg):not(svg *)" +
        ":not(img):not(video):not(canvas):not(i):not([class*=\"icon\" i])" +
        ":not([class*=\"badge\" i]):not([class*=\"btn\" i]) {",
      "    background-color: transparent !important;",
      "    color: inherit !important;",
      "}",
      "",
      "header, nav, aside, footer, [role=\"navigation\"], [role=\"banner\"], [role=\"complementary\"],",
      ".card, .container, .sidebar, .navbar, .box, .panel, .dialog, .modal {",
      "    background-color: var(--surface_container) !important;",
      "    border-color: var(--outline_variant) !important;",
      "    color: var(--on_surface) !important;",
      "}",
      "",
      "code, pre, kbd, samp {",
      "    background-color: var(--surface_container_high) !important;",
      "    color: var(--on_surface) !important;",
      "    border-color: var(--outline_variant) !important;",
      "}",
      "",
      "a:any-link { color: var(--primary) !important; }",
      "a:any-link:hover { color: var(--primary_fixed) !important; }",
      "a:visited { color: var(--tertiary) !important; }",
      "",
      "input:not([type=\"submit\"]):not([type=\"button\"]):not([type=\"reset\"])" +
        "     :not([type=\"checkbox\"]):not([type=\"radio\"]), textarea, select {",
      "    background-color: var(--surface_container_low) !important;",
      "    color: var(--on_surface) !important;",
      "    border: 1px solid var(--outline) !important;",
      "    caret-color: var(--primary) !important;",
      "}",
      "::placeholder { color: var(--on_surface_variant) !important; opacity: 1 !important; }",
      "",
      "button, input[type=\"submit\"], input[type=\"button\"], .btn, .button {",
      "    background-color: var(--primary) !important;",
      "    color: var(--on_primary) !important;",
      "    border: none !important;",
      "}",
      "button:hover, input[type=\"submit\"]:hover { background-color: var(--primary_fixed) !important; }",
      "",
      "table, th, td { border-color: var(--outline_variant) !important; }",
      "th { background-color: var(--surface_container_high) !important; color: var(--on_surface) !important; }",
      "tr:nth-child(even) td { background-color: var(--surface_container_low) !important; }",
      "",
      "::selection { background: var(--primary_container) !important; color: var(--on_primary_container) !important; }",
    ].join("\n");
  }

  const indent = (lines) => lines.map((l) => (l ? "    " + l : "")).join("\n");

  // Filter out unused raw palette swatch dumps (e.g. pink-100..900, orange-100..900)
  function isSemanticThemeVar(name) {
    const n = name.toLowerCase();
    if (/^--(pink|orange|yellow|purple|cyan|teal|lime|amber|violet|fuchsia|rose|emerald|sky)-[0-9]+[a-z]?$/.test(n)) {
      return false;
    }
    return true;
  }

  function scan() {
    customPropIndex = null;
    const groups = new Map();
    const unmapped = [];
    let found = 0;

    for (const [name, rawValue] of collectVariables()) {
      if (skipVar(name) || !isSemanticThemeVar(name)) continue;
      const col = parseCssColor(rawValue);
      if (!col || col.a === 0) continue;
      found++;
      const token = matchKnownFramework(name) || classifyByValueAndName(name, col);
      if (!token || !TOKEN_NAMES.has(token)) { unmapped.push(name); continue; }
      if ("--" + token === name) continue;
      const key = col.shape === "rgb-triplet" ? token + "\u0000rgb"
                : col.shape === "hsl-triplet" ? token + "\u0000hsl" : token;
      (groups.get(key) ?? groups.set(key, []).get(key)).push(name);
    }

    const body = [];
    let mapped = 0;

    if (groups.size) {
      body.push(`${detectRootScopes()} {`, "    color-scheme: dark !important;");
      for (const [token] of TOKENS) {
        for (const suffix of ["", "\u0000rgb", "\u0000hsl"]) {
          const names = groups.get(token + suffix);
          if (!names) continue;
          const label = suffix === "\u0000rgb" ? `${token} (rgb components)`
                      : suffix === "\u0000hsl" ? `${token} (hsl components)` : token;
          body.push(`    /* ${label} */`);
          for (const n of names.sort()) {
            body.push(`    ${n}: var(--${token}) !important;`);
            mapped++;
          }
        }
      }
      body.push("}");
    } else {
      body.push(structuralFallback());
      mapped = 1;
    }

    if (unmapped.length) {
      const sorted = unmapped.sort();
      const shown = sorted.slice(0, 30).join(", ") +
        (sorted.length > 30 ? `, +${sorted.length - 30} more` : "");
      body.push("", `/* unmapped: ${shown} */`);
    }

    return { ok: true, found, mapped, body: indent(body.join("\n").split("\n")) };
  }

  /* ══ VISUAL PICKER ═════════════════════════════════════════════════════ */
  const S = {
    active: false, hydrated: false, note: "", rev: 0,
    rules: [], undo: [], redo: [], stack: [], depth: 0,
    locked: false, targetMode: "selector", group: "bg",
    elementVars: [], dialogPos: null, raf: 0, saveSeq: 0, saving: null,
  };

  const KEY_RE = /\/\*\s*dusky\s+key=([^\s*]+)\s*(?:\|\s*(.*?)\s*)?\*\/\s*$/;

  function splitRule(text) {
    let depth = 0, inStr = 0, selEnd = -1, bodyStart = -1, bodyEnd = -1;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inStr) { if (c === "\\") i++; else if (c === inStr) inStr = 0; continue; }
      if (c === '"' || c === "'") { inStr = c; continue; }
      if (c === "{") { if (depth++ === 0) { selEnd = i; bodyStart = i + 1; } continue; }
      if (c === "}") { if (--depth === 0) { bodyEnd = i; break; } }
    }
    if (selEnd < 0 || bodyEnd < 0) return null;
    return { sel: text.slice(0, selEnd).trim(), decl: text.slice(bodyStart, bodyEnd).trim() };
  }

  function parseRule(line) {
    const trimmed = line.trim();
    if (!trimmed) return null;
    const km = KEY_RE.exec(trimmed);
    const [, rawKey = "", rawMeta = ""] = km || [];
    const key = rawKey ? decodeURIComponent(rawKey) : "";
    const meta = rawMeta;
    const css = km ? trimmed.slice(0, km.index).trim() : trimmed;
    const parts = splitRule(css);
    if (!parts) return { raw: css, key: key || "raw\u001F" + css, meta: meta || "manual" };
    return {
      sel: parts.sel,
      decl: parts.decl,
      meta: meta || "restored",
      key: key || "sel\u001F" + parts.sel + "\u001F" + (parts.decl.split(":")[0] || "?").trim(),
    };
  }

  const ruleCss = (r) => (r.raw !== undefined ? r.raw : `${r.sel} { ${r.decl} }`);
  const ruleLine = (r) =>
    `${ruleCss(r)} /* dusky key=${encodeURIComponent(r.key)}${r.meta ? " | " + r.meta : ""} */`;

  const target = () => S.stack.at(S.depth) ?? null;
  const ROOT_ARMOR = ":root:root:root";

  const GROUPS = {
    bg:     { extra: { label: "👻 Transparent",   css: "background: transparent !important; box-shadow: none !important;", meta: "bg: transparent" } },
    text:   { extra: { label: "↩ Inherit colour", css: "color: inherit !important;",         meta: "text: inherit" } },
    border: { extra: { label: "⊘ No border",      css: "border-color: transparent !important;", meta: "border: none" } },
    fill:   { extra: { label: "🎨 currentColor",  css: "fill: currentColor !important;",     meta: "fill: currentColor" } },
  };

  const PAIRED_ON = {
    primary: "on_primary", primary_container: "on_primary_container",
    secondary: "on_secondary", secondary_container: "on_secondary_container",
    tertiary: "on_tertiary", tertiary_container: "on_tertiary_container",
    error: "on_error", error_container: "on_error", background: "on_background",
  };

  function declFor(group, token) {
    if (group === "text") return `color: var(--${token}) !important;`;
    if (group === "border") return `border-color: var(--${token}) !important;`;
    if (group === "fill") return `fill: var(--${token}) !important; color: var(--${token}) !important;`;
    const on = PAIRED_ON[token] ?? (token.startsWith("surface") ? "on_surface" : "");
    return `background-color: var(--${token}) !important;` +
      (on ? ` color: var(--${on}) !important; border-color: var(--outline_variant) !important;` : "");
  }

  const important = (text) =>
    text.split(";").map((d) => d.trim()).filter(Boolean)
        .map((d) => (/!important$/i.test(d) ? d : d + " !important") + ";").join(" ");

  function getElementVars(elm) {
    if (elm?.nodeType !== 1) return [];
    const cs = getComputedStyle(elm);
    const seen = new Set();
    const out = [];
    const add = (prop) => {
      if (!prop.startsWith("--") || skipVar(prop) || seen.has(prop)) return;
      const v = cs.getPropertyValue(prop).trim();
      if (!v) return;
      seen.add(prop);
      out.push({ name: prop, value: v.length > 44 ? v.slice(0, 41) + "…" : v });
    };

    for (const cls of elm.classList) {
      const arb = /^[a-z-]+-\((--[\w-]+)\)$/.exec(cls);
      if (arb) {
        const [, arbVar] = arb;
        add(arbVar);
      }
      const tok = /^[a-z-]+-token-([\w-]+)$/.exec(cls);
      if (tok) {
        const [, tokName] = tok;
        add("--" + tokName);
      }
    }
    for (const p of elm.style) add(p);
    for (const { sel, props } of propIndex()) {
      let hit = false;
      try { hit = elm.matches(sel); } catch { continue; }
      if (hit) for (const p of props) add(p);
    }
    for (const prop of ["background-color", "color", "border-color", "fill"]) {
      const used = /var\((--[\w-]+)/.exec(cs.getPropertyValue(prop));
      if (used) {
        const [, usedVar] = used;
        add(usedVar);
      }
    }
    return out;
  }

  /* ── Live style injection ────────────────────────────────────────────── */
  const liveStyle = document.createElement("style");
  const hoverStyle = document.createElement("style");
  function mountStyles() {
    if (!liveStyle.isConnected) (document.head || document.documentElement).append(liveStyle, hoverStyle);
  }
  const renderLive = () => { mountStyles(); liveStyle.textContent = S.rules.map(ruleCss).join("\n"); };
  const setHover = (css) => { mountStyles(); hoverStyle.textContent = css || ""; };

  /* ── Shadow UI ───────────────────────────────────────────────────────── */
  const UI_CSS = `
:host{all:initial!important;display:block!important;position:fixed!important;inset:0 auto auto 0!important;width:0!important;height:0!important;overflow:visible!important;z-index:2147483647!important;pointer-events:none!important;isolation:isolate!important}
*{box-sizing:border-box}
.mask{position:fixed;z-index:2147483646;display:none;pointer-events:none!important;border-radius:4px;outline:2px dashed #e6c280;box-shadow:0 0 0 200vmax rgba(18,15,12,.6)}
.panel{position:fixed;z-index:2147483647;pointer-events:auto;background:#191614;color:#f5ebe0;border:1px solid #d4a359;border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.85);font:12px/1.4 system-ui,sans-serif;user-select:none}
.bar{top:12px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:8px;padding:6px 10px;white-space:nowrap;cursor:grab;touch-action:none;max-width:calc(100vw - 24px)}
.grip{opacity:.5;padding:0 2px;cursor:grab}
.title{font-weight:700;color:#e6c280}
.info{max-width:340px;overflow:hidden;text-overflow:ellipsis;color:#c4b8aa;font:11px ui-monospace,monospace}
.state{font-size:11px;color:#c4b8aa}.state.ok{color:#81c784}.state.err{color:#e57373}.state.warn{color:#e6c280}
button{font:inherit;color:#f5ebe0;background:#2d2722;border:1px solid #3d342c;border-radius:6px;padding:4px 8px;cursor:pointer;white-space:nowrap}
button:hover:not(:disabled){border-color:#d4a359}button:disabled{opacity:.4;cursor:default}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #e6c280;outline-offset:1px}
.x{background:#b8545e;border-color:#b8545e;color:#fff;font-weight:700}
.grow{flex:1}
.dlg{top:64px;right:16px;width:430px;max-width:calc(100vw - 32px);max-height:calc(100vh - 96px);overflow:auto;padding:12px;outline:none;transition:opacity .15s}
.dlg.ghost:not(:hover):not(:focus-within){opacity:.25}
.head{display:flex;align-items:center;gap:6px;padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid #3d342c;cursor:grab;touch-action:none}
.head .title{flex:1}
.row{display:flex;align-items:center;gap:6px;margin:6px 0}
.lbl{flex:none;width:68px;color:#c4b8aa;font-size:11px}
.tag{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e6c280;font:11px ui-monospace,monospace}
input[type=range]{flex:1;accent-color:#e6c280;margin:0}
select,input[type=text]{flex:1;min-width:0;font:11px ui-monospace,monospace;color:#f5ebe0;background:#25201c;border:1px solid #3d342c;border-radius:6px;padding:5px 6px;user-select:text}
.seg{flex:1;display:flex}.seg button{flex:1;border-radius:0}.seg button:first-child{border-radius:6px 0 0 6px}.seg button:last-child{border-radius:0 6px 6px 0}
.seg button[aria-pressed=true]{background:#e6c280;border-color:#e6c280;color:#191614;font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin:8px 0;max-height:236px;overflow-y:auto}
.grid button{display:flex;align-items:center;gap:7px;text-align:left;padding:4px 7px}
.sw{flex:none;width:13px;height:13px;border-radius:50%;border:1px solid #55493d}
.hint{margin:8px 0 0;color:#8f857a;font-size:10.5px}
.drawer{bottom:16px;right:16px;width:400px;max-width:calc(100vw - 32px);max-height:60vh;padding:12px;display:flex;flex-direction:column}
.list{overflow:auto;display:flex;flex-direction:column;gap:4px}
.item{display:flex;align-items:center;gap:6px;padding:4px 6px;background:#25201c;border:1px solid #3d342c;border-radius:6px}
.item:hover{border-color:#d4a359}
.item .sel{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:11px ui-monospace,monospace}
.item .meta{flex:none;color:#e6c280;font-size:10.5px}
.item button{padding:1px 6px}`;

  const BAR_HTML = `
<span class="grip" aria-hidden="true">⠿</span>
<span class="title">🎯 Dusky picker</span>
<span class="info" id="binfo"></span>
<span class="state" id="bstate"></span>
<button id="bundo" title="Undo (Ctrl+Z)">↶</button>
<button id="bredo" title="Redo (Ctrl+Shift+Z)">↷</button>
<button id="brules" title="Rules saved for this site">Rules</button>
<button id="bexit" class="x" title="Stop picking (Esc)">✕ Exit</button>`;

  const DIALOG_HTML = `
<div class="head" id="dhead">
  <span class="grip" aria-hidden="true">⠿</span>
  <span class="title">🎨 Theme this element</span>
  <button id="dghost" title="See-through while pointer is elsewhere" aria-pressed="false">👁</button>
  <button id="dclose" title="Close (Esc)">✕</button>
</div>
<div class="row"><span class="lbl">Element</span><span class="tag" id="dtag"></span></div>
<div class="row"><span class="lbl">Depth</span>
  <button id="dchild" title="Down (↓)">↓ child</button>
  <input type="range" id="dslider" min="0" max="0" value="0" aria-label="DOM depth">
  <button id="dparent" title="Up (↑)">↑ parent</button>
</div>
<div class="row"><span class="lbl">Target</span>
  <div class="seg" id="dmode-seg" role="group" aria-label="Target mode">
    <button data-mode="selector" aria-pressed="true">Element selector</button>
    <button data-mode="variable" aria-pressed="false" id="dmode-var-btn">CSS variable</button>
  </div>
</div>
<div class="row" id="dsel-row"><span class="lbl">Selector</span><select id="dsel" aria-label="CSS selector"></select></div>
<div class="row" id="dvar-row" hidden><span class="lbl">Variable</span><select id="dvar" aria-label="CSS variable"></select></div>
<div class="row" id="dprop-row"><span class="lbl">Property</span>
  <div class="seg" id="dseg" role="group" aria-label="Property">
    <button data-group="bg" aria-pressed="true">Background</button>
    <button data-group="text" aria-pressed="false">Text</button>
    <button data-group="border" aria-pressed="false">Border</button>
    <button data-group="fill" aria-pressed="false">Fill (SVG)</button>
  </div>
</div>
<div class="grid" id="dgrid"></div>
<div class="row">
  <button id="dextra" class="grow"></button>
  <button id="dhide" class="x grow" title="display:none — Shift+click on page does this">🙈 Hide element</button>
</div>
<div class="row">
  <input type="text" id="dcustom" placeholder="custom CSS, e.g. border-radius: 8px; opacity: .9" aria-label="Custom CSS">
  <button id="dapply">Apply</button>
</div>
<p class="hint">Hover swatch to preview · click to save · ↑ ↓ depth · Esc closes</p>`;

  const DRAWER_HTML = `
<div class="head" id="rhead">
  <span class="grip" aria-hidden="true">⠿</span>
  <span class="title">📋 Rules for this site</span>
  <button id="rclear" class="x" title="Remove every rule (Ctrl+Z restores)">Clear all</button>
  <button id="rclose" title="Close">✕</button>
</div>
<div class="list" id="rlist"></div>
<p class="hint">Hover a rule to highlight · ✕ removes it · saved into the picks region</p>`;

  const hostEl = document.createElement("dusky-picker");
  for (const [p, v] of Object.entries({
    all: "initial", display: "block", position: "fixed", top: "0", left: "0",
    width: "0", height: "0", overflow: "visible", "z-index": "2147483647",
    "pointer-events": "none", isolation: "isolate",
  })) hostEl.style.setProperty(p, v, "important");

  const root = hostEl.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>${UI_CSS}</style><div class="mask" id="mask"></div>`;
  const q = (id) => root.getElementById(id);
  const isOurs = (e) => e.composedPath().includes(hostEl);

  let bar = null, dialog = null, drawer = null;

  function el(tag, attrs, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs ?? {})) {
      if (k === "text") n.textContent = v;
      else if (k === "class") n.className = v;
      else if (k === "style") Object.assign(n.style, v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "disabled") n.disabled = !!v;
      else n.setAttribute(k, v);
    }
    n.append(...children);
    return n;
  }

  function drag(panel, handle, onMove) {
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button,input,select,textarea,a,[contenteditable]")) return;
      const r = panel.getBoundingClientRect();
      const ox = e.clientX - r.left, oy = e.clientY - r.top, w = r.width, h = r.height;
      const ctl = new AbortController();
      const move = (ev) => {
        const x = Math.min(Math.max(0, ev.clientX - ox), Math.max(0, innerWidth - w));
        const y = Math.min(Math.max(0, ev.clientY - oy), Math.max(0, innerHeight - h));
        Object.assign(panel.style, { left: `${x}px`, top: `${y}px`, right: "auto", bottom: "auto", transform: "none" });
        onMove?.(x, y);
      };
      handle.setPointerCapture(e.pointerId);
      handle.addEventListener("pointermove", move, { signal: ctl.signal });
      handle.addEventListener("pointerup", () => ctl.abort(), { signal: ctl.signal });
      handle.addEventListener("pointercancel", () => ctl.abort(), { signal: ctl.signal });
      e.preventDefault();
      e.stopPropagation();
    });
  }

  function drawMask() {
    const m = q("mask"), t = target();
    if (!t?.isConnected) { m.style.display = "none"; return; }
    const r = t.getBoundingClientRect();
    Object.assign(m.style, {
      display: "block", left: `${r.left}px`, top: `${r.top}px`,
      width: `${r.width}px`, height: `${r.height}px`,
    });
  }
  const scheduleMask = () => {
    S.raf ||= requestAnimationFrame(() => { S.raf = 0; drawMask(); });
  };

  const SKIP_CLASS = /^(is-|has-|js-|dusky)|^(active|selected|open|hover|focus|focused|visible|hidden|show|shown|collapsed|expanded|disabled|checked|current)$/;
  const HASHY = /^(css|sc|jsx|jss|svelte|emotion)-|^_[a-z0-9]+$|__[a-z0-9]{5,}$\vert{}^[^-_]*\d[^-_]*$/i;
  const HASHY_ID = /^(radix|aria|headlessui|react-select|__next|mui|floating-ui)-|^:[a-z0-9]+:$/i;
  const TW_UTILITY = /^(flex|grid|block|inline|inline-flex|inline-block|contents|table|hidden|grow|shrink|relative|absolute|fixed|sticky|static|isolate|overflow-.*|truncate|antialiased|box-border|box-content|z-.*|w-.*|h-.*|size-.*|min-w-.*|max-w-.*|min-h-.*|max-h-.*|[pm][trblxy]?-.*|inset-.*|top-.*|left-.*|right-.*|bottom-.*|col-.*|row-.*|order-.*|basis-.*|items-.*|justify-.*|content-.*|place-.*|self-.*|gap-.*|space-.*|divide-.*|cursor-.*|select-.*|pointer-events-.*|rounded.*|shadow.*|opacity-.*|transition.*|duration-.*|ease-.*|animate-.*|scale-.*|rotate-.*|translate-.*|font-.*|text-.*|leading-.*|tracking-.*|whitespace-.*|break-.*|align-.*|list-.*|underline|uppercase|lowercase|capitalize|bg-.*|from-.*|via-.*|to-.*|border(-.*)?|ring-.*|outline-.*|fill-.*|stroke-.*|group|peer|sr-only|not-sr-only)$/i;

  const goodClasses = (n) => [...n.classList].filter((c) =>
    !SKIP_CLASS.test(c) && !HASHY.test(c) && !TW_UTILITY.test(c) &&
    !c.includes(":") && !c.includes("(") && !c.includes("/") && !c.includes("[")
  ).slice(0, 3);

  const simple = (n) => n.localName + goodClasses(n).map((c) => "." + CSS.escape(c)).join("");
  const describe = (n) => simple(n) + (n.id && !HASHY_ID.test(n.id) && !HASHY.test(n.id) ? "#" + CSS.escape(n.id) : "");
  const usableId = (n) => !!n.id && !HASHY.test(n.id) && !HASHY_ID.test(n.id);
  const attrStr = (v) => '"' + v.replaceAll(/["\\]/g, "\\$&") + '"';

  function pathSel(n) {
    const parts = [];
    for (let cur = n;
         cur && cur !== document.body && cur !== document.documentElement && parts.length < 3;
         cur = cur.parentElement) {
      if (usableId(cur)) { parts.unshift("#" + CSS.escape(cur.id)); break; }
      let s = simple(cur);
      const sibs = cur.parentElement ? [...cur.parentElement.children] : [];
      let ambiguous = false;
      try { ambiguous = sibs.some((c) => c !== cur && c.matches(s)); } catch { ambiguous = false; }
      if (ambiguous) {
        s += `:nth-of-type(${sibs.filter((c) => c.localName === cur.localName).indexOf(cur) + 1})`;
      }
      parts.unshift(s);
    }
    return parts.join(" > ") || n.localName;
  }

  function candidates(n) {
    if (!n || n === document.documentElement) return [{ sel: "html", count: 1 }];
    if (n === document.body) return [{ sel: "body", count: 1 }];
    const out = [];
    if (usableId(n)) out.push("#" + CSS.escape(n.id));
    const s = simple(n);
    if (s !== n.localName) out.push(s);
    for (const a of ["role", "aria-label", "data-testid", "data-test-id", "name"]) {
      const v = n.getAttribute(a);
      if (v && v.length < 60) out.push(`${n.localName}[${a}=${attrStr(v)}]`);
    }
    out.push(pathSel(n), n.localName);
    const seen = new Set();
    return out.filter((sel) => !seen.has(sel) && seen.add(sel)).map((sel) => {
      let count = 0;
      try { count = document.querySelectorAll(sel).length; } catch { /* invalid */ }
      return { sel, count };
    }).filter((c) => c.count > 0);
  }

  function buildBar() {
    bar = el("section", { class: "panel bar", role: "toolbar", "aria-label": "Dusky picker" });
    bar.innerHTML = BAR_HTML;
    root.append(bar);
    drag(bar, bar);
    q("bundo").addEventListener("click", undo);
    q("bredo").addEventListener("click", redo);
    q("brules").addEventListener("click", toggleDrawer);
    q("bexit").addEventListener("click", () => setActive(false));
    if (S.note) setState("⚠ not saving: " + S.note, "err");
    else if (!paletteLoaded()) setState("⚠ palette variables not loaded on this page", "warn");
    refreshBar();
  }

  function refreshBar() {
    if (!bar) return;
    const t = target();
    q("binfo").textContent = t
      ? `<${describe(t)}>${S.stack.length > 1 ? `  · depth ${S.depth}/${S.stack.length - 1}` : ""}`
      : "Hover element · click to theme · Shift+click hides · Esc exits";
    q("bundo").disabled = !S.undo.length;
    q("bredo").disabled = !S.redo.length;
    q("brules").textContent = `Rules (${S.rules.length})`;
  }

  function setState(text, cls) {
    const s = q("bstate");
    if (s) { s.textContent = text; s.className = "state " + cls; }
  }

  const selected = () => (dialog ? q("dsel").value : candidates(target()).at(0)?.sel ?? "");

  function outline(extra) {
    if (S.targetMode === "variable") { setHover(""); return; }
    const sel = selected();
    if (!sel) { setHover(""); return; }
    setHover(`${sel}{outline:2px dashed #e6c280 !important;outline-offset:-2px !important}` +
             (extra ? `\n${sel}{${extra}}` : ""));
  }

  function openDialog() {
    dialog?.remove();
    dialog = el("section", { class: "panel dlg", role: "dialog", "aria-label": "Theme this element", tabindex: "-1" });
    dialog.innerHTML = DIALOG_HTML;
    if (S.dialogPos) Object.assign(dialog.style, { left: `${S.dialogPos.x}px`, top: `${S.dialogPos.y}px`, right: "auto" });
    root.append(dialog);
    drag(dialog, q("dhead"), (x, y) => { S.dialogPos = { x, y }; });

    const t = target();
    S.elementVars = getElementVars(t);
    S.group = t?.closest("svg") ? "fill" : "bg";
    S.targetMode = "selector";

    q("dclose").addEventListener("click", closeDialog);
    q("dghost").addEventListener("click", (e) => {
      e.currentTarget.setAttribute("aria-pressed", String(dialog.classList.toggle("ghost")));
    });
    q("dslider").addEventListener("input", (e) => { S.depth = Number(e.target.value); retarget(); });
    q("dchild").addEventListener("click", () => step(-1));
    q("dparent").addEventListener("click", () => step(1));
    q("dsel").addEventListener("change", () => outline());

    const modeSeg = q("dmode-seg"), varBtn = q("dmode-var-btn");
    varBtn.disabled = S.elementVars.length === 0;
    varBtn.title = varBtn.disabled
      ? "No CSS custom properties detected on this element"
      : `${S.elementVars.length} variable(s) detected`;

    modeSeg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-mode]");
      if (!b || b.disabled) return;
      S.targetMode = b.dataset.mode;
      for (const x of modeSeg.children) x.setAttribute("aria-pressed", String(x === b));
      const isVar = S.targetMode === "variable";
      q("dsel-row").hidden = isVar;
      q("dprop-row").hidden = isVar;
      q("dvar-row").hidden = !isVar;
      outline();
    });

    const dseg = q("dseg");
    for (const x of dseg.children) x.setAttribute("aria-pressed", String(x.dataset.group === S.group));
    dseg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-group]");
      if (!b) return;
      S.group = b.dataset.group;
      for (const x of dseg.children) x.setAttribute("aria-pressed", String(x === b));
      q("dextra").textContent = GROUPS[S.group].extra.label;
      outline();
    });

    const grid = q("dgrid");
    for (const [token, label] of TOKENS) {
      const b = el("button", { title: `var(--${token})` },
        el("i", { class: "sw", style: { background: `var(--${token}, transparent)` } }),
        el("span", { text: label }));
      b.addEventListener("mouseenter", () => { if (S.targetMode === "selector") outline(declFor(S.group, token)); });
      b.addEventListener("mouseleave", () => outline());
      b.addEventListener("click", () => {
        if (S.targetMode === "variable") {
          const v = q("dvar").value;
          if (v) applyVar(v, token);
        } else {
          apply(declFor(S.group, token), `${S.group}: ${token}`, S.group);
        }
      });
      grid.append(b);
    }

    const extra = q("dextra");
    extra.textContent = GROUPS[S.group].extra.label;
    extra.addEventListener("mouseenter", () => { if (S.targetMode === "selector") outline(GROUPS[S.group].extra.css); });
    extra.addEventListener("mouseleave", () => outline());
    extra.addEventListener("click", () => apply(GROUPS[S.group].extra.css, GROUPS[S.group].extra.meta, S.group));

    const hide = q("dhide");
    hide.addEventListener("mouseenter", () => outline("display:none !important;"));
    hide.addEventListener("mouseleave", () => outline());
    hide.addEventListener("click", () => apply("display: none !important;", "hidden", "display"));

    const custom = q("dcustom");
    const applyCustom = () => {
      const v = custom.value.trim();
      if (v) apply(important(v), "custom", "custom");
    };
    q("dapply").addEventListener("click", applyCustom);
    custom.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); applyCustom(); }
    });

    refreshDialog();
    dialog.focus({ preventScroll: true });
  }

  function refreshDialog() {
    const t = target();
    if (!dialog || !t) return;
    q("dtag").textContent = `<${describe(t)}>`;
    const sl = q("dslider");
    sl.max = String(Math.max(0, S.stack.length - 1));
    sl.value = String(S.depth);
    q("dchild").disabled = S.depth === 0;
    q("dparent").disabled = S.depth >= S.stack.length - 1;

    const sel = q("dsel");
    sel.textContent = "";
    for (const c of candidates(t)) {
      sel.append(el("option", { value: c.sel, text: `${c.sel}   — ${c.count} match${c.count === 1 ? "" : "es"}` }));
    }
    const dvar = q("dvar");
    dvar.textContent = "";
    for (const v of S.elementVars) dvar.append(el("option", { value: v.name, text: `${v.name}  =  ${v.value}` }));
    outline();
  }

  function closeDialog() {
    dialog?.remove();
    dialog = null;
    S.locked = false;
    setHover("");
  }

  const selKey = (sel, group) => `sel\u001F${sel}\u001F${group}`;
  const varKey = (sel, name) => `var\u001F${sel}\u001F${name}`;

  function upsert(rule) {
    snapshot();
    const i = S.rules.findIndex((r) => r.key === rule.key);
    if (i >= 0) S.rules[i] = rule; else S.rules.push(rule);
    commit();
  }

  function apply(decl, meta, group) {
    const sel = selected();
    if (!sel) return;
    upsert({ sel, decl, meta, key: selKey(sel, group) });
    closeDialog();
  }

  function applyVar(varName, token) {
    upsert({
      sel: ROOT_ARMOR,
      decl: `${varName}: var(--${token}) !important;`,
      meta: `var ${varName} → ${token}`,
      key: varKey(ROOT_ARMOR, varName),
    });
    closeDialog();
  }

  function toggleDrawer() {
    if (drawer) { drawer.remove(); drawer = null; return; }
    drawer = el("section", { class: "panel drawer", role: "dialog", "aria-label": "Rules for this site" });
    drawer.innerHTML = DRAWER_HTML;
    root.append(drawer);
    drag(drawer, q("rhead"));
    q("rclose").addEventListener("click", toggleDrawer);
    q("rclear").addEventListener("click", () => {
      if (S.rules.length) { snapshot(); S.rules = []; commit(); }
    });
    refreshDrawer();
  }

  function refreshDrawer() {
    if (!drawer) return;
    const list = q("rlist");
    list.textContent = "";
    if (!S.rules.length) {
      list.append(el("p", { class: "hint", text: "No rules yet — click any element on the page." }));
      return;
    }
    S.rules.forEach((r, i) => {
      const item = el("div", { class: "item" },
        el("span", { class: "sel", title: ruleLine(r), text: r.raw !== undefined ? r.raw : r.sel }),
        el("span", { class: "meta", text: r.meta || "manual" }),
        el("button", {
          title: "Remove this rule", text: "✕",
          onclick: () => { snapshot(); S.rules.splice(i, 1); commit(); },
        }));
      if (r.raw === undefined) {
        item.addEventListener("mouseenter", () =>
          setHover(`${r.sel}{outline:2px dashed #e6c280 !important;outline-offset:-2px !important}`));
        item.addEventListener("mouseleave", () => (dialog ? outline() : setHover("")));
      }
      list.append(item);
    });
  }

  function snapshot() {
    S.undo.push(S.rules.slice());
    if (S.undo.length > 100) S.undo.shift();
    S.redo = [];
  }
  const undo = () => { if (S.undo.length) { S.redo.push(S.rules); S.rules = S.undo.pop(); commit(); } };
  const redo = () => { if (S.redo.length) { S.undo.push(S.rules); S.rules = S.redo.pop(); commit(); } };
  const commit = () => { renderLive(); refreshBar(); refreshDrawer(); void persist(); };

  const serialise = () => S.rules.map((r) => "    " + ruleLine(r)).join("\n");

  function mergeForeign(foreignPicks) {
    const mine = new Map(S.rules.map((r) => [r.key, r]));
    const merged = [];
    for (const line of String(foreignPicks || "").split("\n")) {
      const r = parseRule(line);
      if (!r) continue;
      if (mine.has(r.key)) { merged.push(mine.get(r.key)); mine.delete(r.key); }
      else merged.push(r);
    }
    merged.push(...mine.values());
    S.rules = merged;
  }

  async function persist() {
    const seq = ++S.saveSeq;
    setState("saving…", "");
    S.saving = (async () => {
      let reply = await send({ type: "splice", region: "picks", body: serialise(), base_rev: S.rev });
      if (reply?.conflict) {
        mergeForeign(reply.picks);
        renderLive(); refreshBar(); refreshDrawer();
        S.rev = reply.rev ?? 0;
        reply = await send({ type: "splice", region: "picks", body: serialise(), base_rev: S.rev });
      }
      if (seq !== S.saveSeq) return;
      if (reply?.ok) {
        S.rev = reply.rev ?? 0;
        setState("✓ saved " + String(reply.path).split("/").pop(), "ok");
      } else {
        setState("⚠ not saved: " + (reply?.error ?? "no reply"), "err");
      }
    })();
    return S.saving;
  }

  const send = (msg) => browser.runtime.sendMessage(msg)
    .catch((e) => ({ ok: false, error: String(e?.message ?? e) }));

  async function hydrate(force = false) {
    if (S.hydrated && !force) return;
    const reply = await send({ type: "read" });
    if (reply?.ok) {
      S.hydrated = true;
      S.note = "";
      S.rev = reply.rev ?? 0;
      S.rules = String(reply.picks || "").split("\n").map(parseRule).filter(Boolean);
    } else {
      S.note = reply?.error ?? "cannot reach native host";
    }
  }

  function setStack(elm) {
    const chain = [];
    for (let n = elm; n?.nodeType === 1; n = n.parentElement) chain.push(n);
    S.stack = chain;
    S.depth = 0;
    retarget();
  }
  const retarget = () => { drawMask(); refreshBar(); refreshDialog(); };
  function step(delta) {
    if (!S.stack.length) return;
    S.depth = Math.min(Math.max(0, S.depth + delta), S.stack.length - 1);
    retarget();
  }
  function typing() {
    const a = root.activeElement ?? document.activeElement;
    return !!a && (a.isContentEditable || /^(input|select|textarea)$/i.test(a.tagName));
  }

  const onOver = (e) => { if (!S.locked && !isOurs(e)) setStack(e.target); };
  const onPointerDown = (e) => {
    if (isOurs(e)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
  };
  function onClick(e) {
    if (isOurs(e)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!S.stack.length) setStack(e.target);
    if (e.shiftKey) {
      const sel = candidates(target()).at(0)?.sel;
      if (sel) upsert({ sel, decl: "display: none !important;", meta: "hidden", key: selKey(sel, "display") });
      return;
    }
    S.locked = true;
    openDialog();
  }
  function onKey(e) {
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    if (k === "Escape") {
      if (dialog) closeDialog();
      else if (drawer) toggleDrawer();
      else void setActive(false);
    } else if (typing()) return;
    else if (k === "ArrowUp" || k === "ArrowDown") {
      if (!S.stack.length) return;
      step(k === "ArrowUp" ? 1 : -1);
    } else if (ctrl && !e.altKey && k.toLowerCase() === "z") { e.shiftKey ? redo() : undo(); }
    else if (ctrl && !e.altKey && k.toLowerCase() === "y") redo();
    else return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }
  const LISTENERS = [["mouseover", onOver], ["pointerdown", onPointerDown], ["click", onClick], ["keydown", onKey]];

  let listenerCtl = null;

  async function setActive(on) {
    if (on === S.active) return;
    S.active = on;
    if (on) {
      customPropIndex = null;
      await hydrate(true);
      document.documentElement.append(hostEl);
      buildBar();
      renderLive();
      listenerCtl = new AbortController();
      const opts = { capture: true, signal: listenerCtl.signal };
      for (const [type, fn] of LISTENERS) window.addEventListener(type, fn, opts);
      window.addEventListener("scroll", scheduleMask, { capture: true, passive: true, signal: listenerCtl.signal });
      window.addEventListener("resize", scheduleMask, { passive: true, signal: listenerCtl.signal });
    } else {
      closeDialog();
      if (drawer) toggleDrawer();
      bar?.remove();
      bar = null;
      listenerCtl?.abort();
      listenerCtl = null;
      S.stack = [];
      S.depth = 0;
      S.locked = false;
      customPropIndex = null;
      drawMask();
      hostEl.remove();
      dropProbe();
      await S.saving?.catch(() => {});
    }
  }

  browser.runtime.onMessage.addListener((msg) => {
    switch (msg?.type) {
      case "ping":
        return Promise.resolve({ ok: true, active: S.active, rules: S.rules.length });
      case "scan":
        try { return Promise.resolve(scan()); }
        catch (e) { return Promise.resolve({ ok: false, error: "Scan failed: " + (e?.message ?? e) }); }
      case "picker":
        return setActive(msg.enable ?? !S.active).then(() => ({ ok: true, active: S.active }));
      case "reset":
        S.rules = []; S.undo = []; S.redo = []; S.hydrated = true; S.note = ""; S.rev = 0;
        renderLive(); refreshBar(); refreshDrawer();
        return Promise.resolve({ ok: true });
      case "rehydrate":
        return hydrate(true).then(() => {
          renderLive(); refreshBar(); refreshDrawer();
          return { ok: true, rules: S.rules.length };
        });
      default:
        return false;
    }
  });
})();
