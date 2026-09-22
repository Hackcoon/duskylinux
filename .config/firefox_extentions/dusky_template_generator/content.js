/*
 * Dusky Template Generator — content.js (Gecko 156+)
 *
 * Two jobs, one file:
 *   1. scan()  — colour-token scanner behind the popup's Auto-map button;
 *   2. picker  — an in-page, closed-shadow-DOM element picker that owns the
 *                "picks" region of $XDG_CONFIG_HOME/dusky_sites/<domain>.css.
 *
 * CASCADE CONTRACT (v4 — this is what makes previews and themes reliable):
 *   All injected CSS lives in ONE constructable stylesheet adopted by the
 *   document, structured as
 *       @layer dusky.preview, dusky.live;
 *   CSS Cascade 5 reverses layer order for !important declarations: the
 *   EARLIEST layer wins, and layered !important beats unlayered !important.
 *   Therefore  preview  ≻  live  ≻  the site's own !important rules,
 *   independently of specificity, source order, and anything the page does to
 *   <head>. Hover preview is consequently identical in pick and edit mode.
 *
 * Reliability contract:
 *   · nothing is written unless the picks region was read first (hydrated);
 *   · every write carries base_rev; a conflict re-reads, merges (local wins
 *     per key) and retries with backoff;
 *   · writes are serialised and coalesced by generation — a burst is one write.
 *
 * Rule identity (unchanged wire protocol): one rule per line, trailed by a
 * "dusky key=<strict-urlencoded-key> | <meta>" CSS comment. Key shapes:
 *   sel\u001F<selector>\u001F<group>   group: bg|text|border|fill|display|custom:<props>
 *   var\u001F<scope>\u001F<--name>
 *   raw\u001F<css>                     hand-written line we could not parse
 */
"use strict";
(() => {
  if (globalThis.__duskyTemplateGenerator) return;
  globalThis.__duskyTemplateGenerator = true;

  /* ══ Material 3 palette contract ════════════════════════════════════ */
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

  /* Everything Matugen itself injects. Exact names only: a prefix regex also
   * swallows real site tokens such as --error_bg, --surface_alt, --primary_hover. */
  const PALETTE_OWNED = new Set([
    ...TOKEN_NAMES,
    "error_container", "on_error_container", "inverse_primary",
    "on_primary_fixed", "on_primary_fixed_variant",
    "secondary_fixed", "on_secondary_fixed",
    "tertiary_fixed", "tertiary_fixed_dim", "on_tertiary_fixed", "on_tertiary_fixed_variant",
    "scrim", "shadow", "source_color", "surface_tint",
  ]);
  const PALETTE_SUFFIX = /_(rgb|rgba|hex|hsl|raw|strip)$/;
  /* Framework internals that are never site design tokens. --mui-* and --wp--*
   * are deliberately NOT here: those are mappable palettes. */
  const NOISE_RE = /^--(tw-|fa-|dusky|darkreader|chakra-emotion)/i;

  const skipVar = (name) => {
    if (typeof name !== "string" || !name.startsWith("--")) return true;
    if (NOISE_RE.test(name)) return true;
    return PALETTE_OWNED.has(name.slice(2).toLowerCase().replace(PALETTE_SUFFIX, ""));
  };

  const paletteLoaded = () =>
    getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() !== "";

  /* ══ Shadow host + closed root (also hosts the colour probe) ═════════ */
  const hostEl = document.createElement("dusky-picker");
  for (const [p, v] of Object.entries({
    all: "initial", display: "block", position: "fixed", top: "0", left: "0",
    width: "0", height: "0", overflow: "visible", "z-index": "2147483647",
    "pointer-events": "none", isolation: "isolate",
  })) hostEl.style.setProperty(p, v, "important");
  const root = hostEl.attachShadow({ mode: "closed" });

  /* ══ Perceptual colour engine ═══════════════════════════════════════ */
  /* The probe lives in a detached element inside the closed root: the page can
   * neither see it nor style it, and it never triggers layout. */
  let colorProbe = null;
  const getProbe = () => (colorProbe ??= document.createElement("span"));
  const dropProbe = () => { colorProbe = null; };

  const RGB_OUT = /^(?:rgb|rgba)\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.%]+))?\s*\)$/i;
  const IS_COLOR_SYNTAX =
    /^(#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark)\()/i;
  const HSL_TRIPLET = /^(-?[\d.]+)(?:deg)?\s+([\d.]+)%\s+([\d.]+)%$/;
  const RGB_TRIPLET = /^(\d{1,3})[,\s]+(\d{1,3})[,\s]+(\d{1,3})$/;
  const KEYWORDISH = /^(inherit|initial|unset|revert|revert-layer|transparent|currentcolor|none)$/i;

  function parseCssColor(raw) {
    if (typeof raw !== "string") return null;
    const v = raw.trim();
    if (!v || KEYWORDISH.test(v)) return null;

    const hsl = v.match(HSL_TRIPLET);
    const triplet = !hsl && v.match(RGB_TRIPLET);
    if (triplet) {
      const [, r, g, b] = triplet.map(Number);
      return r <= 255 && g <= 255 && b <= 255 ? { r, g, b, a: 1, shape: "rgb-triplet" } : null;
    }
    /* Reject non-colours early so font/spacing variables never leak through. */
    if (!(hsl || IS_COLOR_SYNTAX.test(v) || CSS.supports("color", v))) return null;

    const probe = getProbe();
    probe.style.color = "";
    probe.style.color = hsl ? `hsl(${v})` : v;
    if (!probe.style.color) return null;                /* the parser refused it */

    /* Detached elements have no computed style, so resolve through the CSSOM:
     * style.color is already serialised by the parser into a canonical form. */
    const serialised = probe.style.color;
    const match = RGB_OUT.exec(serialised) ?? RGB_OUT.exec(resolveViaRoot(serialised));
    if (!match) return null;
    const [, rs, gs, bs, as] = match;
    const alpha = as === undefined ? 1 : (as.endsWith("%") ? parseFloat(as) / 100 : parseFloat(as));
    return {
      r: Math.round(+rs), g: Math.round(+gs), b: Math.round(+bs), a: alpha,
      shape: hsl ? "hsl-triplet" : "color",
    };
  }

  /* Canonicalise exotic colour syntaxes (oklch, color-mix, light-dark) to rgb()
   * using a one-shot computed-value round trip on the shadow root's own node. */
  let resolver = null;
  function resolveViaRoot(value) {
    if (!resolver?.isConnected) {
      resolver = document.createElement("i");
      resolver.style.cssText = "display:none!important";
      root.append(resolver);
    }
    resolver.style.color = "";
    resolver.style.color = value;
    return getComputedStyle(resolver).color ?? "";
  }

  const srgb = (c) => ((c /= 255), c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
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

  /* ══ Framework signature table ══════════════════════════════════════ */
  const SHADCN = {
    "--background": "background", "--foreground": "on_background",
    "--card": "surface_container", "--card-foreground": "on_surface",
    "--popover": "surface_container_high", "--popover-foreground": "on_surface",
    "--primary": "primary", "--primary-foreground": "on_primary",
    "--secondary": "secondary_container", "--secondary-foreground": "on_secondary_container",
    "--muted": "surface_container_low", "--muted-foreground": "on_surface_variant",
    "--accent": "surface_container_high", "--accent-foreground": "on_surface",
    "--destructive": "error", "--destructive-foreground": "on_error",
    "--border": "outline_variant", "--input": "outline", "--ring": "primary",
    "--sidebar": "surface_container", "--sidebar-background": "surface_container",
    "--sidebar-foreground": "on_surface", "--sidebar-primary": "primary",
    "--sidebar-accent": "surface_container_high", "--sidebar-border": "outline_variant",
    "--sidebar-ring": "primary",
  };

  const MATERIAL = {
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
    "background-default": "background", "background-paper": "surface_container",
    "text-primary": "on_surface", "text-secondary": "on_surface_variant",
    "divider": "outline_variant",
  };

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

    /* Google Material / Gemini / MUI */
    if (n.startsWith("--gem-sys-color--") || n.startsWith("--mat-") ||
        n.startsWith("--bard-color-") || n.startsWith("--mui-palette-")) {
      const tail = n.replace(/^--(gem-sys-color--|mat-|bard-color-|mui-palette-)/, "").replaceAll("-main", "");
      if (MATERIAL[tail]) return MATERIAL[tail];
      if (tail.includes("app-text-color")) return "on_surface";
      if (tail.includes("background-color")) return "surface";
    }

    /* Tailwind v4 / shadcn / Radix */
    if (SHADCN[n]) return SHADCN[n];

    /* Discord */
    if (n.startsWith("--neutral-")) {
      const step = Number.parseInt(n.slice(10), 10);
      if (Number.isFinite(step)) {
        if (step >= 90) return "surface";
        if (step >= 84) return "surface_container_low";
        if (step >= 78) return "surface_container";
        if (step >= 70) return "surface_container_high";
        if (step <= 10) return "on_surface";
        if (step <= 30) return "on_surface_variant";
      }
    }
    if (n.startsWith("--brand-") || n.startsWith("--blurple-")) {
      if (n.includes("560")) return "on_primary_container";
      if (n.includes("10a") || n.includes("highlight")) return "inverse_on_surface";
      if (n.includes("60")) return "secondary_container";
      if (n.includes("50") || n.includes("65")) return "primary_container";
      return "primary";
    }

    /* Instagram */
    if (n.startsWith("--ig-")) {
      if (n.includes("primary-background")) return "surface";
      if (n.includes("elevated-background")) return "surface_container_low";
      if (n.includes("separator")) return "outline_variant";
      if (n.includes("-text") || n.includes("-icon")) return "on_surface";
    }

    /* Chess.com */
    if (n.startsWith("--color-gray-") || n.startsWith("--gray-")) {
      const step = Number.parseInt(n.replace(/\D+/g, ""), 10);
      if (step >= 800) return "surface";
      if (step >= 700) return "surface_container";
      if (step >= 600) return "surface_container_high";
      if (step >= 500) return "surface_container_highest";
      if (step >= 400) return "surface_bright";
    }
    if (n.includes("green-200")) return "primary_fixed";
    if (n.includes("green-300")) return "primary";
    if (n.includes("green-400") || n.includes("green-500")) return "primary_container";
    if (n.includes("neutrals-white")) return "on_surface";

    /* Telegram */
    if (n.includes("chat-hover")) return "surface_container_high";
    if (n.includes("chat-active")) return "primary_container";
    if (n.includes("bg-color-secondary")) return "surface_container_lowest";
    if (n.includes("compact-menu")) return "surface_container_low";
    if (n === "--theme-background-color" || n.includes("theme-bg")) return "surface";
    if (n === "--color-text" || n.includes("color-text-secondary")) return "on_surface_variant";

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

    if (lum <= 0.02) return /(body|canvas|bg-base|root|background|black)/.test(n)
      ? "background" : "surface_container_lowest";
    if (lum <= 0.06) return /(input|field|inset|sunken|deep)/.test(n) ? "surface_container_low" : "surface";
    if (lum <= 0.12) return /(card|panel|box|container|sidebar|nav)/.test(n)
      ? "surface_container" : "surface_container_low";
    if (lum <= 0.22) return /(modal|dialog|popover|dropdown|menu|toast|elevated)/.test(n)
      ? "surface_container_high" : "surface_container";
    if (lum <= 0.38) return /(hover|active|bright)/.test(n) ? "surface_bright" : "surface_container_highest";
    if (lum >= 0.70) return /(muted|secondary|dim|subtle|caption|hint|disabled|placeholder)/.test(n)
      ? "on_surface_variant" : "on_surface";
    return "on_surface_variant";
  }

  /* ══ Stylesheet traversal ═══════════════════════════════════════════ */
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
  let indexWatermark = -1;

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

  /* Invalidate when the document gains or loses a stylesheet (SPA chunks). */
  function propIndex() {
    if (customPropIndex === null || indexWatermark !== document.styleSheets.length) {
      customPropIndex = buildCustomPropIndex();
      indexWatermark = document.styleSheets.length;
    }
    return customPropIndex;
  }
  const dropIndex = () => { customPropIndex = null; indexWatermark = -1; };

  /* Escape for use inside a quoted CSS attribute value. CSS.escape() is the
   * wrong tool here — it escapes identifiers, not string contents. */
  const cssString = (v) => `"${String(v).replaceAll(/["\\]/g, "\\$&")}"`;

  function detectRootScopes() {
    const inner = new Set();
    for (const el of [document.documentElement, document.body].filter(Boolean)) {
      for (const cls of el.classList) {
        if (/^(dark|dark-theme|theme-dark|dark-mode|night)$/i.test(cls)) inner.add(`.${CSS.escape(cls)}`);
      }
      for (const attr of el.getAttributeNames()) {
        if (/^(data-theme|data-color-mode|data-bs-theme|theme|dark)$/i.test(attr)) {
          const val = el.getAttribute(attr);
          inner.add(val ? `[${attr}=${cssString(val)}]` : `[${attr}]`);
        }
      }
    }
    inner.add("[dark]").add(".dark").add('[data-theme="dark"]');
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

  /* Broad structural repaint, used ONLY when the page exposes fewer than three
   * mappable tokens (the popup double-confirms before this is written). */
  function structuralFallback() {
    return [
      "/* Structural theme — this page exposes no usable design tokens. */",
      "html, body {",
      "    background-color: var(--surface) !important;",
      "    color: var(--on_surface) !important;",
      "    color-scheme: dark !important;",
      "}",
      ":not(a):not(button):not(input):not(select):not(textarea):not(code):not(pre)",
      ":not(table):not(svg):not(img):not(video):not([class*='icon']):not([class*='badge']):not([class*='btn']) {",
      "    background-color: transparent !important;",
      "    color: inherit !important;",
      "}",
      "header, nav, aside, footer, main > section, article,",
      "[class*='card'], [class*='panel'], [class*='sidebar'], dialog, [role='dialog'] {",
      "    background-color: var(--surface_container) !important;",
      "    border-color: var(--outline_variant) !important;",
      "    color: var(--on_surface) !important;",
      "}",
      "code, pre, kbd, samp {",
      "    background-color: var(--surface_container_high) !important;",
      "    color: var(--on_surface) !important;",
      "}",
      "a { color: var(--primary) !important; }",
      "a:hover { color: var(--primary_fixed) !important; }",
      "a:visited { color: var(--tertiary) !important; }",
      "input, select, textarea {",
      "    background-color: var(--surface_container_low) !important;",
      "    color: var(--on_surface) !important;",
      "    border-color: var(--outline) !important;",
      "}",
      "button, [type='submit'], [role='button'] {",
      "    background-color: var(--primary) !important;",
      "    color: var(--on_primary) !important;",
      "    border-color: var(--outline_variant) !important;",
      "}",
      "table, th, td { border-color: var(--outline_variant) !important; }",
      "th { background-color: var(--surface_container_high) !important; }",
      "hr { border-color: var(--outline_variant) !important; }",
      "::selection {",
      "    background-color: var(--primary_container) !important;",
      "    color: var(--on_primary_container) !important;",
      "}",
      "::placeholder { color: var(--on_surface_variant) !important; }",
      "* { scrollbar-color: var(--outline) var(--surface_container_low) !important; }",
    ].join("\n");
  }

  const indent = (lines) => lines.map((l) => (l ? `    ${l}` : "")).join("\n");

  /* Raw swatch dumps (pink-100 … pink-900) are not semantic theme tokens. */
  const SWATCH_DUMP =
    /^--(pink|orange|yellow|purple|cyan|teal|lime|amber|violet|fuchsia|rose|emerald|sky)-[0-9]+[a-z]?$/;
  const isSemanticThemeVar = (name) => !SWATCH_DUMP.test(name.toLowerCase());

  function scan() {
    dropIndex();
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
      if (`--${token}` === name) continue;
      const key = col.shape === "rgb-triplet" ? `${token}\u0000rgb`
        : col.shape === "hsl-triplet" ? `${token}\u0000hsl` : token;
      (groups.get(key) ?? groups.set(key, []).get(key)).push(name);
    }

    const body = [];
    let mapped = 0;
    let variableCount = 0;
    for (const list of groups.values()) variableCount += list.length;

    /* Fewer than three mappable variables means the page is not variable
     * driven; only then do we reach for the (very broad) structural theme. */
    const kind = variableCount >= 3 ? "tokens" : "structural";

    if (kind === "tokens") {
      body.push(`${detectRootScopes()} {`, "    color-scheme: dark !important;");
      for (const [token] of TOKENS) {
        for (const suffix of ["", "\u0000rgb", "\u0000hsl"]) {
          const names = groups.get(token + suffix);
          if (!names) continue;
          const label = suffix === "\u0000rgb" ? `${token} (rgb components)`
            : suffix === "\u0000hsl" ? `${token} (hsl components)` : token;
          body.push(`    /* ${label} */`);
          for (const n of names.toSorted()) {
            body.push(`    ${n}: var(--${token}) !important;`);
            mapped++;
          }
        }
      }
      body.push("}");
    } else {
      body.push(structuralFallback());
      mapped = variableCount || 1;
    }

    if (unmapped.length) {
      const sorted = unmapped.toSorted();
      const shown = sorted.slice(0, 30).join(", ") +
        (sorted.length > 30 ? `, +${sorted.length - 30} more` : "");
      body.push("", `/* unmapped: ${shown} */`);
    }

    dropProbe();
    return {
      ok: true, kind, found, mapped, palette: paletteLoaded(),
      body: indent(body.join("\n").split("\n")),
    };
  }

  /* ══ VISUAL PICKER ══════════════════════════════════════════════════ */
  const LIMITS = { RULES: 600, DECL: 4096, SEL: 512, BODY: 512 * 1024 };

  const S = {
    active: false, hydrated: false, note: "", rev: 0, warnings: [],
    rules: Object.freeze([]), undo: [], redo: [], stack: [], depth: 0,
    locked: false, targetMode: "selector", group: "bg",
    elementVars: [], panelPos: null, raf: 0, editKey: null, generation: 0,
  };

  const US = "\u001F";
  const ROOT_ARMOR = ":root:root:root";
  const ORIGIN = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  /* ── Rule model ────────────────────────────────────────────────────── */
  /* encodeURIComponent leaves !'()* alone and KEY_RE stops at '*', so a
   * selector like [class*="icon"] would round-trip TRUNCATED. Escape the full
   * RFC 3986 sub-delims set. */
  const enc = (s) => encodeURIComponent(String(s))
    .replaceAll(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
  const dec = (s) => { try { return decodeURIComponent(s); } catch { return s; } };
  const KEY_RE = /\/\*\s*dusky\s+key=([^\s*|]+)\s*(?:\|\s*([^*]*?)\s*)?\*\/\s*$/;

  const oneLine = (s) => String(s ?? "").replaceAll(/\s*[\r\n]+\s*/g, " ").trim();
  const safeMeta = (s) => oneLine(s).replaceAll("*/", "* /").slice(0, 160);

  const selKey = (sel, group) => `sel${US}${sel}${US}${group}`;
  const varKey = (scope, name) => `var${US}${scope}${US}${name}`;
  const rawKey = (css) => `raw${US}${css}`;

  /* One parser for every key shape — no more positional indexing. */
  function decodeKey(key) {
    const [kind, a, b] = String(key ?? "").split(US);
    if (kind === "var" && a && b?.startsWith("--")) return { kind: "var", scope: a, name: b };
    if (kind === "raw" && a !== undefined) return { kind: "raw", css: a };
    if (kind === "sel" && a && b) return { kind: "sel", sel: a, group: b };
    return { kind: "invalid" };
  }

  const propsOf = (decl) => [...new Set(String(decl).split(";")
    .map((d) => d.split(":")[0].trim().toLowerCase()).filter(Boolean))].toSorted();

  const PROP_GROUP = [
    [/^background(-color|-image)?$/, "bg"], [/^color$/, "text"],
    [/^border(-[a-z]+)?-color$/, "border"], [/^fill$/, "fill"], [/^display$/, "display"],
  ];
  function groupOfDecl(decl) {
    const props = propsOf(decl);
    const first = props[0] ?? "";
    if (first.startsWith("--")) return "var";
    for (const [re, g] of PROP_GROUP) if (re.test(first)) return g;
    return `custom:${props.join(",")}`;
  }
  const tokenOf = (decl) => /var\(\s*--([a-z0-9_]+)/i.exec(String(decl ?? ""))?.[1] ?? "";

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
    const storedKey = km ? dec(km[1]) : "";
    const meta0 = km ? (km[2] ?? "").trim() : "";
    const css = km ? trimmed.slice(0, km.index).trim() : trimmed;
    if (!css) return null;

    const parts = splitRule(css);
    if (!parts?.sel || !parts?.decl) {
      return { raw: css, meta: meta0 || "manual", key: rawKey(css) };
    }
    const decl = oneLine(parts.decl);
    const group = groupOfDecl(decl);
    const derived = group === "var" ? varKey(parts.sel, propsOf(decl)[0]) : selKey(parts.sel, group);
    /* A stored key is honoured only when it parses AND its shape matches the
     * CSS it labels; otherwise the CSS is authoritative (self-healing files). */
    const stored = decodeKey(storedKey);
    const keep = stored.kind === "var"
      ? group === "var" && stored.scope === parts.sel
      : stored.kind === "sel" && group !== "var" && stored.sel === parts.sel;
    return { sel: parts.sel, decl, meta: meta0 || "restored", key: keep ? storedKey : derived };
  }
  const parseLines = (text) => String(text ?? "").split("\n").map(parseRule).filter(Boolean);

  const ruleCss = (r) => (r.raw !== undefined ? r.raw : `${r.sel} { ${r.decl} }`);
  const ruleLine = (r) =>
    `${ruleCss(r)} /* dusky key=${enc(r.key)}${r.meta ? ` | ${safeMeta(r.meta)}` : ""} */`;
  const serialise = () => S.rules.map((r) => `    ${ruleLine(r)}`).join("\n");

  const target = () => S.stack.at(S.depth) ?? null;

  const GROUPS = {
    bg: { label: "Background", extra: { label: "👻 Transparent", css: "background: transparent !important; box-shadow: none !important;", meta: "bg: transparent" } },
    text: { label: "Text", extra: { label: "↩ Inherit colour", css: "color: inherit !important;", meta: "text: inherit" } },
    border: { label: "Border", extra: { label: "⊘ No border", css: "border-color: transparent !important;", meta: "border: none" } },
    fill: { label: "Fill", extra: { label: "🎨 currentColor", css: "fill: currentColor !important;", meta: "fill: currentColor" } },
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
  const colourGroup = (g) => (GROUPS[g] ? g : "bg");

  const important = (text) => text.split(";").map((d) => d.trim()).filter(Boolean)
    .map((d) => `${/!important\s*$/i.test(d) ? d : `${d} !important`};`).join(" ");

  function validSelector(sel) {
    if (typeof sel !== "string" || !sel || sel.length > LIMITS.SEL) return false;
    try { document.querySelector(sel); return true; } catch { return false; }
  }

  /* Validate a declaration list by parsing it into a detached style object. */
  function normaliseDecl(text) {
    const src = oneLine(text);
    if (!src || src.length > LIMITS.DECL) return "";
    const probe = document.createElement("div");
    try { probe.style.cssText = src; } catch { return ""; }
    if (!probe.style.length && !/--[\w-]+\s*:/.test(src)) return "";
    return important(src);
  }

  function getElementVars(elm) {
    if (elm?.nodeType !== 1) return [];
    const cs = getComputedStyle(elm);
    const seen = new Set();
    const out = [];
    const add = (prop) => {
      if (!prop?.startsWith("--") || skipVar(prop) || seen.has(prop)) return;
      const v = cs.getPropertyValue(prop).trim();
      if (!v) return;
      seen.add(prop);
      out.push({ name: prop, value: v.length > 44 ? `${v.slice(0, 41)}…` : v });
    };
    for (const cls of elm.classList) {
      add(/^[a-z-]+-\((--[\w-]+)\)$/.exec(cls)?.[1]);
      const tok = /^[a-z-]+-token-([\w-]+)$/.exec(cls)?.[1];
      if (tok) add(`--${tok}`);
    }
    for (const p of elm.style) add(p);
    for (const { sel, props } of propIndex()) {
      let hit = false;
      try { hit = elm.matches(sel); } catch { continue; }
      if (hit) for (const p of props) add(p);
    }
    for (const prop of ["background-color", "color", "border-color", "fill"]) {
      add(/var\((--[\w-]+)/.exec(cs.getPropertyValue(prop))?.[1]);
    }
    return out;
  }

  /* ══ STYLE ENGINE — one adopted sheet, two cascade layers ═══════════ */
  /* @layer dusky.preview, dusky.live;  ⇒ for !important declarations the
   * EARLIEST layer wins (CSS Cascade 5 §layer ordering), so the preview always
   * beats the live rule, and both beat the site's unlayered !important CSS. */
  const SHEET = new CSSStyleSheet();
  let liveCss = "";
  let previewCss = "";

  function flushSheet() {
    SHEET.replaceSync(
      "@layer dusky.preview, dusky.live;\n" +
      `@layer dusky.live{\n${liveCss}\n}\n` +
      `@layer dusky.preview{\n${previewCss}\n}\n`,
    );
    if (!document.adoptedStyleSheets.includes(SHEET)) {
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, SHEET];
    }
  }
  function detachSheet() {
    liveCss = previewCss = "";
    document.adoptedStyleSheets = document.adoptedStyleSheets.filter((s) => s !== SHEET);
  }

  const renderLive = () => { liveCss = S.rules.map(ruleCss).join("\n"); flushSheet(); };

  const OUTLINE = "outline:2px dashed #e6c280 !important;outline-offset:-2px !important";

  /* THE single preview entry point — pick mode, edit mode, chips, drawer rows
   * and the extra buttons all go through here, so they cannot diverge. */
  const Preview = {
    show(spec) {
      if (!spec) return Preview.clear();
      const chunks = [];
      if (spec.highlight && validSelector(spec.highlight)) {
        chunks.push(`${spec.highlight}{${OUTLINE}}`);
      }
      if (spec.css) chunks.push(spec.css);
      previewCss = chunks.join("\n");
      flushSheet();
    },
    clear() { previewCss = ""; flushSheet(); },
  };

  /* Build a preview spec for ANY rule key + token. Used by edit mode. */
  function previewForKey(key, sel, decl, token) {
    const k = decodeKey(key);
    if (k.kind === "var") {
      const scope = sel || k.scope || ROOT_ARMOR;
      return token
        ? { highlight: scope === ROOT_ARMOR ? "" : scope, css: `${scope}{${k.name}: var(--${token}) !important}` }
        : { highlight: scope === ROOT_ARMOR ? "" : scope, css: "" };
    }
    if (k.kind === "raw") return { highlight: "", css: "" };
    const useSel = sel || k.sel;
    if (!token) return { highlight: useSel, css: "" };
    if (k.group === "display") {
      /* A hidden element cannot show a colour: preview the un-hide instead. */
      return { highlight: useSel, css: `${useSel}{display:revert !important;${OUTLINE}}` };
    }
    if (k.group?.startsWith("custom:")) {
      /* Substitute the token into the existing var() if the rule has one,
       * otherwise just highlight — never lie with an unrelated background. */
      const swapped = String(decl ?? "").replaceAll(/var\(\s*--[a-z0-9_]+/gi, `var(--${token}`);
      return { highlight: useSel, css: swapped === decl ? "" : `${useSel}{${swapped}}` };
    }
    return { highlight: useSel, css: `${useSel}{${declFor(colourGroup(k.group), token)}}` };
  }

  /* ══ Shadow UI ══════════════════════════════════════════════════════ */
  const UI_CSS = `
:host{all:initial!important;display:block!important;position:fixed!important;inset:0 auto auto 0!important;width:0!important;height:0!important;overflow:visible!important;z-index:2147483647!important;pointer-events:none!important;isolation:isolate!important}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
button,input,select,textarea{font:inherit;color:inherit;background:none;border:0}
.mask{position:fixed;display:none;pointer-events:none;outline:2px dashed #e6c280;outline-offset:-2px;background:rgba(230,194,128,.07);border-radius:2px}
.panel{position:fixed;pointer-events:auto;background:#191614;color:#f5ebe0;border:1px solid #3d342c;border-radius:10px;box-shadow:0 14px 44px rgba(0,0,0,.65);font:13px/1.45 system-ui,sans-serif;display:flex;flex-direction:column;gap:6px;padding:8px;transition:opacity .12s ease}
.panel.ghost{opacity:.25}
.panel.ghost:hover,.panel.ghost:focus-within{opacity:1}
.bar{top:10px;left:50%;transform:translateX(-50%);flex-direction:row;align-items:center;gap:6px;padding:6px 8px;max-width:min(96vw,980px)}
.dlg{top:64px;right:16px;width:440px;max-height:calc(100vh - 88px);overflow:auto}
.drawer{right:16px;bottom:16px;width:420px;max-height:62vh;overflow:hidden}
.head{display:flex;align-items:center;gap:6px;cursor:grab;user-select:none}
.head:active{cursor:grabbing}
.grip{color:#6d645a;font-size:12px}
.title{flex:1;font-weight:700;color:#e6c280;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.info{color:#c4b8aa;font:11.5px ui-monospace,monospace;max-width:38ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.state{font-size:11px;color:#c4b8aa;max-width:34ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.state.ok{color:#81c784}.state.err{color:#e57373}.state.warn{color:#e6c280}
.panel button{cursor:pointer;background:#2d2722;border:1px solid #3d342c;border-radius:7px;padding:4px 8px;color:#f5ebe0;white-space:nowrap}
.panel button:hover:not(:disabled){border-color:#d4a359}
.panel button:disabled{opacity:.4;cursor:default}
.panel button:focus-visible,.panel select:focus-visible,.panel input:focus-visible,.panel textarea:focus-visible{outline:2px solid #e6c280;outline-offset:1px}
.panel button.x{border-color:#6d3b40;color:#ffb4ab}
.panel button.grow{flex:1;justify-content:center;text-align:center}
.row{display:flex;align-items:center;gap:6px}
.lbl{flex:0 0 68px;color:#8f857a;font-size:11.5px}
.tag{flex:1;font:11.5px ui-monospace,monospace;color:#e6c280;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.panel select,.panel input[type=text],.panel textarea{flex:1;min-width:0;background:#0f0d0c;border:1px solid #3d342c;border-radius:7px;padding:4px 6px;font:11.5px ui-monospace,monospace;color:#f5ebe0}
.panel textarea{min-height:64px;resize:vertical}
.panel input[type=range]{flex:1;accent-color:#e6c280}
.seg{display:flex;flex:1;gap:2px;background:#0f0d0c;border:1px solid #3d342c;border-radius:7px;padding:2px}
.seg button{flex:1;border:0;background:transparent;padding:3px 4px;font-size:11.5px;border-radius:5px}
.seg button[aria-pressed=true]{background:#e6c280;color:#191614;font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:3px;max-height:230px;overflow:auto;padding:2px;border:1px solid #2a231d;border-radius:8px;background:#0f0d0c}
.grid button{display:flex;align-items:center;gap:6px;border:1px solid transparent;background:transparent;padding:3px 5px;font-size:11.5px;text-align:left;overflow:hidden}
.grid button:hover{background:#241f1a;border-color:#3d342c}
.grid button.act{border-color:#e6c280}
.grid button.act .lab::after{content:" ✓";color:#e6c280}
.sw{flex:0 0 13px;height:13px;border-radius:50%;border:1px solid #00000066;box-shadow:inset 0 0 0 1px #ffffff14}
.lab{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chips{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.cap{width:100%;color:#8f857a;font-size:10.5px}
.chip{display:flex;align-items:center;gap:5px;max-width:200px;font-size:11px}
.dot{flex:0 0 10px;height:10px;border-radius:50%;border:1px solid #00000066}
.hint{color:#8f857a;font-size:10.5px}
.list{overflow:auto;display:flex;flex-direction:column;gap:3px;padding-right:2px}
.item{display:flex;gap:4px}
.item .open{flex:1;display:flex;align-items:center;gap:6px;overflow:hidden}
.item .sel{flex:1;font:11px ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .meta{color:#8f857a;font-size:10.5px;white-space:nowrap}
`;

  const BAR_HTML = `
<span class="grip" aria-hidden="true">⠿</span>
<span class="title">🎯 Dusky picker</span>
<span class="info" id="binfo"></span>
<span class="state" id="bstate"></span>
<button id="bundo" title="Undo (Ctrl+Z)">↶</button>
<button id="bredo" title="Redo (Ctrl+Shift+Z)">↷</button>
<button id="bsync" title="Re-read this site's file from disk">⟲</button>
<button id="brules" title="Rules saved for this site — click one to recolour it">Rules</button>
<button id="bexit" class="x" title="Stop picking (Esc)">✕ Exit</button>`;

  const PICK_HTML = `
<div class="head" id="phead">
  <span class="grip" aria-hidden="true">⠿</span>
  <span class="title">🎨 Theme this element</span>
  <button id="pghost" title="See-through while the pointer is elsewhere" aria-pressed="false">👁</button>
  <button id="pclose" title="Close (Esc)">✕</button>
</div>
<div class="row"><span class="lbl">Element</span><span class="tag" id="ptag"></span></div>
<div class="row"><span class="lbl">Depth</span>
  <button id="pchild" title="Down (↓)">↓ child</button>
  <input type="range" id="pslider" min="0" max="0" value="0" aria-label="DOM depth">
  <button id="pparent" title="Up (↑)">↑ parent</button>
</div>
<div class="row"><span class="lbl">Target</span>
  <div class="seg" id="pmode" role="group" aria-label="Target mode">
    <button data-mode="selector" aria-pressed="true">Element selector</button>
    <button data-mode="variable" aria-pressed="false" id="pvarbtn">CSS variable</button>
  </div>
</div>
<div class="row" id="psel-row"><span class="lbl">Selector</span><select id="psel" aria-label="CSS selector"></select></div>
<div class="row" id="pvar-row" hidden><span class="lbl">Variable</span><select id="pvar" aria-label="CSS variable"></select></div>
<div class="row" id="pscope-row" hidden><span class="lbl">Scope</span><select id="pscope" aria-label="Override scope"></select></div>
<div class="row" id="pprop-row"><span class="lbl">Property</span>
  <div class="seg" id="pseg" role="group" aria-label="Property">
    <button data-group="bg" aria-pressed="true">Background</button>
    <button data-group="text" aria-pressed="false">Text</button>
    <button data-group="border" aria-pressed="false">Border</button>
    <button data-group="fill" aria-pressed="false">Fill (SVG)</button>
  </div>
</div>
<div class="chips" id="pexist"></div>
<div id="pgrid"></div>
<div class="row">
  <button id="pextra" class="grow"></button>
  <button id="phide" class="x grow" title="display:none — Shift+click on the page does this">🙈 Hide element</button>
</div>
<div class="row">
  <input type="text" id="pcustom" spellcheck="false" placeholder="custom CSS, e.g. border-radius: 8px; opacity: .9" aria-label="Custom CSS">
  <button id="papply">Apply</button>
</div>
<p class="hint">Hover or Tab to a swatch to preview · click/Enter applies — the panel stays open · ↑ ↓ change depth · click the page to move · Esc closes</p>`;

  const EDIT_HTML = `
<div class="head" id="ehead">
  <span class="grip" aria-hidden="true">⠿</span>
  <span class="title">✏️ Edit rule</span>
  <button id="eghost" title="See-through while the pointer is elsewhere" aria-pressed="false">👁</button>
  <button id="eclose" title="Close (Esc)">✕</button>
</div>
<div class="row" id="esel-row"><span class="lbl" id="esel-lbl">Selector</span><input type="text" id="esel" spellcheck="false" aria-label="Selector"></div>
<div class="row" id="evar-row" hidden><span class="lbl">Variable</span><span class="tag" id="evar"></span></div>
<div class="row" id="eprop-row"><span class="lbl">Property</span>
  <div class="seg" id="eseg" role="group" aria-label="Property">
    <button data-group="bg">Background</button>
    <button data-group="text">Text</button>
    <button data-group="border">Border</button>
    <button data-group="fill">Fill (SVG)</button>
  </div>
</div>
<div id="egrid"></div>
<div class="row" id="eraw-row" hidden><textarea id="eraw" spellcheck="false" aria-label="Raw CSS"></textarea></div>
<div class="row" id="ecustom-row">
  <input type="text" id="ecustom" spellcheck="false" placeholder="declaration, e.g. color: var(--primary)" aria-label="Declaration">
  <button id="eapply">Apply</button>
</div>
<div class="row">
  <button id="edelete" class="x grow">🗑 Remove rule</button>
  <button id="edone" class="grow">Done</button>
</div>
<p class="hint" id="ehint"></p>`;

  const DRAWER_HTML = `
<div class="head" id="rhead">
  <span class="grip" aria-hidden="true">⠿</span>
  <span class="title">📋 Rules for this site</span>
  <button id="rclear" class="x" title="Remove every rule (Ctrl+Z restores)">Clear all</button>
  <button id="rclose" title="Close">✕</button>
</div>
<div class="list" id="rlist"></div>
<p class="hint">Click a rule to recolour or edit it · hover highlights it on the page · ✕ removes it</p>`;

  root.adoptedStyleSheets = [(() => { const s = new CSSStyleSheet(); s.replaceSync(UI_CSS); return s; })()];
  root.innerHTML = `<div class="mask" id="mask"></div>`;
  const q = (id) => root.getElementById(id);
  const isOurs = (e) => e.composedPath().includes(hostEl);

  let bar = null, panel = null, panelKind = null, drawer = null;
  /* Every panel publishes how IT previews a token. One contract, two panels. */
  let previewOf = () => null;

  function el(tag, attrs, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs ?? {})) {
      if (v === undefined || v === null) continue;
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

  function drag(p, handle, onMove) {
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button,input,select,textarea,a,[contenteditable]")) return;
      const r = p.getBoundingClientRect();
      const ox = e.clientX - r.left, oy = e.clientY - r.top, w = r.width, h = r.height;
      const ctl = new AbortController();
      const move = (ev) => {
        const x = Math.min(Math.max(0, ev.clientX - ox), Math.max(0, innerWidth - w));
        const y = Math.min(Math.max(0, ev.clientY - oy), Math.max(0, innerHeight - h));
        Object.assign(p.style, { left: `${x}px`, top: `${y}px`, right: "auto", bottom: "auto", transform: "none" });
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
    if (!t?.isConnected || panelKind === "edit") { m.style.display = "none"; return; }
    const r = t.getBoundingClientRect();
    Object.assign(m.style, {
      display: "block", left: `${r.left}px`, top: `${r.top}px`,
      width: `${r.width}px`, height: `${r.height}px`,
    });
  }
  const scheduleMask = () => { S.raf ||= requestAnimationFrame(() => { S.raf = 0; drawMask(); }); };

  /* ── Selector synthesis ────────────────────────────────────────────── */
  const SKIP_CLASS = /^(is-|has-|js-|dusky)|^(active|selected|open|hover|focus|focused|visible|hidden|show|shown|collapsed|expanded|disabled|checked|current)$/;
  /* The v3 literal contained a stray markup artefact ("$\vert{}") which
   * silently disabled the "looks like a hash" branch (\v is a vertical tab). */
  const HASHY = /^(css|sc|jsx|jss|svelte|emotion)-|^_[a-z0-9]+$|__[a-z0-9]{5,}$|^[^-_]*\d[^-_]*$/i;
  const HASHY_ID = /^(radix|aria|headlessui|react-select|__next|mui|floating-ui)-|^:[a-z0-9]+:$/i;
  const TW_UTILITY = /^(flex|grid|block|inline|inline-flex|inline-block|contents|table|hidden|grow|shrink|relative|absolute|fixed|sticky|static|isolate|overflow-.*|truncate|antialiased|box-border|box-content|z-.*|w-.*|h-.*|size-.*|min-w-.*|max-w-.*|min-h-.*|max-h-.*|[pm][trblxy]?-.*|inset-.*|top-.*|left-.*|right-.*|bottom-.*|col-.*|row-.*|order-.*|basis-.*|items-.*|justify-.*|content-.*|place-.*|self-.*|gap-.*|space-.*|divide-.*|cursor-.*|select-.*|pointer-events-.*|rounded.*|shadow.*|opacity-.*|transition.*|duration-.*|ease-.*|animate-.*|scale-.*|rotate-.*|translate-.*|font-.*|text-.*|leading-.*|tracking-.*|whitespace-.*|break-.*|align-.*|list-.*|underline|uppercase|lowercase|capitalize|bg-.*|from-.*|via-.*|to-.*|border(-.*)?|ring-.*|outline-.*|fill-.*|stroke-.*|group|peer|sr-only|not-sr-only)$/i;

  const goodClasses = (n) => [...n.classList].filter((c) =>
    !SKIP_CLASS.test(c) && !HASHY.test(c) && !TW_UTILITY.test(c) &&
    !c.includes(":") && !c.includes("(") && !c.includes("/") && !c.includes("["),
  ).slice(0, 3);

  const simple = (n) => n.localName + goodClasses(n).map((c) => `.${CSS.escape(c)}`).join("");
  const usableId = (n) => !!n.id && !HASHY.test(n.id) && !HASHY_ID.test(n.id);
  const describe = (n) => simple(n) + (usableId(n) ? `#${CSS.escape(n.id)}` : "");

  function pathSel(n) {
    const parts = [];
    for (let cur = n;
      cur && cur !== document.body && cur !== document.documentElement && parts.length < 3;
      cur = cur.parentElement) {
      if (usableId(cur)) { parts.unshift(`#${CSS.escape(cur.id)}`); break; }
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
    if (usableId(n)) out.push(`#${CSS.escape(n.id)}`);
    const s = simple(n);
    if (s !== n.localName) out.push(s);
    for (const a of ["role", "aria-label", "data-testid", "data-test-id", "name"]) {
      const v = n.getAttribute(a);
      if (v && v.length < 60) out.push(`${n.localName}[${a}=${cssString(v)}]`);
    }
    out.push(pathSel(n), n.localName);
    const seen = new Set();
    return out.filter((sel) => !seen.has(sel) && seen.add(sel)).map((sel) => {
      let count = 0;
      try { count = document.querySelectorAll(sel).length; } catch { /* invalid */ }
      return { sel, count };
    }).filter((c) => c.count > 0);
  }

  /* ── Toolbar ───────────────────────────────────────────────────────── */
  function buildBar() {
    bar = el("section", { class: "panel bar", role: "toolbar", "aria-label": "Dusky picker" });
    bar.innerHTML = BAR_HTML;
    root.append(bar);
    drag(bar, bar);
    q("bundo").addEventListener("click", undo);
    q("bredo").addEventListener("click", redo);
    q("bsync").addEventListener("click", () => void recover(true));
    q("brules").addEventListener("click", toggleDrawer);
    q("bexit").addEventListener("click", () => void setActive(false));
    refreshBar();
    baseState();
  }

  function refreshBar() {
    if (!bar) return;
    const t = target();
    q("binfo").textContent = t
      ? `<${describe(t)}>${S.stack.length > 1 ? `  · depth ${S.depth}/${S.stack.length - 1}` : ""}`
      : "Hover an element · click to theme · Shift+click hides · Esc exits";
    q("bundo").disabled = !S.undo.length;
    q("bredo").disabled = !S.redo.length;
    q("brules").textContent = `Rules (${S.rules.length})`;
  }

  let flashTimer = 0;
  function setState(text, cls = "") {
    const s = q("bstate");
    if (s) { s.textContent = text; s.className = `state ${cls}`; }
  }
  function baseState() {
    if (!S.hydrated) setState(`⚠ NOT SAVING — ${S.note || "host unreachable"} · press ⟲`, "err");
    else if (S.warnings.length) setState(`⚠ ${S.warnings[0]}`, "warn");
    else if (!paletteLoaded()) setState("⚠ palette variables not loaded on this page", "warn");
    else setState("", "");
  }
  function flash(text, cls = "ok") {
    clearTimeout(flashTimer);
    setState(text, cls);
    flashTimer = setTimeout(baseState, 2600);
  }

  /* ── Panels ────────────────────────────────────────────────────────── */
  const rememberPos = (x, y) => { S.panelPos = { x, y }; };
  function placePanel(p) {
    if (S.panelPos) Object.assign(p.style, { left: `${S.panelPos.x}px`, top: `${S.panelPos.y}px`, right: "auto" });
  }
  function dropPanel() {
    panel?.remove();
    panel = null;
    panelKind = null;
    previewOf = () => null;
    S.editKey = null;
  }
  function closePanel() {
    dropPanel();
    S.locked = false;
    Preview.clear();
    drawMask();
    refreshBar();
  }
  const refreshPanel = () => {
    if (panelKind === "pick") refreshPick();
    else if (panelKind === "edit") refreshEdit();
  };

  /* ── PaletteGrid: built ONCE, delegated events, never rebuilt ───────
   * This is the structural fix for the dead edit-mode hover: no refresh can
   * destroy the node the pointer is resting on, and pointerover bubbles, so a
   * swatch inserted under a stationary pointer still previews on the next
   * movement (mouseenter, which does not bubble, never would). */
  function PaletteGrid({ onHover, onPick }) {
    const grid = el("div", { class: "grid", role: "listbox", "aria-label": "Palette" });
    const buttons = new Map();
    for (const [token, label] of TOKENS) {
      const b = el("button", { type: "button", "data-token": token, title: `var(--${token})`, tabindex: "-1" },
        el("i", { class: "sw", style: { background: `var(--${token}, transparent)` } }),
        el("span", { class: "lab", text: label }));
      buttons.set(token, b);
      grid.append(b);
    }
    grid.firstElementChild?.setAttribute("tabindex", "0");

    const tokenFrom = (node) => node?.closest?.("button[data-token]")?.dataset.token ?? null;

    grid.addEventListener("pointerover", (e) => { const t = tokenFrom(e.target); if (t) onHover(t); });
    grid.addEventListener("pointerleave", () => onHover(null));
    grid.addEventListener("focusin", (e) => { const t = tokenFrom(e.target); if (t) onHover(t); });
    grid.addEventListener("focusout", (e) => { if (!grid.contains(e.relatedTarget)) onHover(null); });
    grid.addEventListener("click", (e) => { const t = tokenFrom(e.target); if (t) onPick(t); });
    grid.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 2, ArrowUp: -2 }[e.key];
      if (!step) return;
      const items = [...buttons.values()];
      const i = items.indexOf(e.target.closest("button[data-token]"));
      const next = items[Math.min(Math.max(0, i + step), items.length - 1)];
      if (!next || next === e.target) return;
      for (const b of items) b.tabIndex = -1;
      next.tabIndex = 0;
      next.focus();
      e.preventDefault();
      e.stopPropagation();
    });

    return {
      el: grid,
      setActive(token) {
        for (const [name, b] of buttons) b.classList.toggle("act", name === token);
      },
    };
  }

  /* ---- pick panel ---- */
  let pickGrid = null;
  const selected = () => (panelKind === "pick" ? q("psel").value : candidates(target()).at(0)?.sel ?? "");

  function pickPreviewSpec(token) {
    if (S.targetMode === "variable") {
      const name = q("pvar").value;
      const scope = q("pscope").value || ROOT_ARMOR;
      if (!name) return { highlight: "", css: "" };
      return previewForKey(varKey(scope, name), scope, "", token);
    }
    const sel = selected();
    return previewForKey(selKey(sel, S.group), sel, "", token);
  }
  const pickPreview = (token) => Preview.show(pickPreviewSpec(token));

  function openPick() {
    const t = target();
    if (!t) return;
    dropPanel();
    panelKind = "pick";
    S.locked = true;
    S.elementVars = getElementVars(t);
    S.targetMode = "selector";
    if (t.closest("svg") && S.group === "bg") S.group = "fill";

    panel = el("section", { class: "panel dlg", role: "dialog", "aria-label": "Theme this element", tabindex: "-1" });
    panel.innerHTML = PICK_HTML;
    placePanel(panel);
    root.append(panel);
    drag(panel, q("phead"), rememberPos);

    previewOf = pickPreviewSpec;
    pickGrid = PaletteGrid({
      onHover: (token) => Preview.show(previewOf(token)),
      onPick: (token) => {
        if (S.targetMode === "variable") {
          const name = q("pvar").value;
          if (!name) return;
          const sc = q("pscope").value || ROOT_ARMOR;
          upsert({
            sel: sc, decl: `${name}: var(--${token}) !important;`,
            meta: `var ${name} → ${token}`, key: varKey(sc, name),
          });
          flash(`✓ ${name} → ${token}`);
        } else {
          applySel(declFor(S.group, token), `${S.group}: ${token}`, S.group);
        }
      },
    });
    q("pgrid").append(pickGrid.el);

    q("pclose").addEventListener("click", closePanel);
    q("pghost").addEventListener("click", (e) =>
      e.currentTarget.setAttribute("aria-pressed", String(panel.classList.toggle("ghost"))));
    q("pslider").addEventListener("input", (e) => { S.depth = Number(e.target.value); retarget(); });
    q("pchild").addEventListener("click", () => step(-1));
    q("pparent").addEventListener("click", () => step(1));
    for (const id of ["psel", "pvar", "pscope"]) {
      q(id).addEventListener("change", () => refreshPick());
    }

    const varBtn = q("pvarbtn");
    varBtn.disabled = S.elementVars.length === 0;
    varBtn.title = varBtn.disabled
      ? "No CSS custom properties detected on this element"
      : `${S.elementVars.length} variable(s) detected`;
    q("pmode").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-mode]");
      if (!b || b.disabled) return;
      S.targetMode = b.dataset.mode;
      refreshPick();
    });
    q("pseg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-group]");
      if (!b) return;
      S.group = b.dataset.group;
      refreshPick();
    });

    const hoverExtra = (css) => () => {
      if (S.targetMode !== "selector") return;
      const sel = selected();
      Preview.show({ highlight: sel, css: validSelector(sel) ? `${sel}{${css}}` : "" });
    };
    q("pextra").addEventListener("pointerenter", () => hoverExtra(GROUPS[S.group].extra.css)());
    q("pextra").addEventListener("focus", () => hoverExtra(GROUPS[S.group].extra.css)());
    q("pextra").addEventListener("pointerleave", () => pickPreview(null));
    q("pextra").addEventListener("blur", () => pickPreview(null));
    q("pextra").addEventListener("click", () =>
      applySel(GROUPS[S.group].extra.css, GROUPS[S.group].extra.meta, S.group));

    q("phide").addEventListener("pointerenter", hoverExtra("display:none !important;"));
    q("phide").addEventListener("pointerleave", () => pickPreview(null));
    q("phide").addEventListener("click", () => applySel("display: none !important;", "hidden", "display"));

    const custom = q("pcustom");
    const applyCustom = () => {
      const decl = normaliseDecl(custom.value);
      if (!decl) { flash("that is not a valid declaration", "err"); return; }
      applySel(decl, `custom: ${propsOf(decl).join(", ")}`, `custom:${propsOf(decl).join(",")}`);
      custom.value = "";
    };
    q("papply").addEventListener("click", applyCustom);
    custom.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); applyCustom(); }
    });

    refreshPick(true);
    panel.focus({ preventScroll: true });
  }

  function rulesTouching(t) {
    if (!t) return [];
    const cands = new Set(candidates(t).map((c) => c.sel));
    const vars = new Set(S.elementVars.map((v) => v.name));
    return S.rules.filter((r) => {
      const k = decodeKey(r.key);
      if (k.kind === "var") return vars.has(k.name);
      if (k.kind === "raw") return false;
      if (cands.has(r.sel)) return true;
      try { return t.matches(r.sel); } catch { return false; }
    });
  }

  let lastPickTarget = null;
  function refreshPick(full = false) {
    const t = target();
    if (panelKind !== "pick" || !t) return;
    const changed = full || t !== lastPickTarget;
    lastPickTarget = t;

    q("ptag").textContent = `<${describe(t)}>`;

    const sl = q("pslider");
    sl.max = String(Math.max(0, S.stack.length - 1));
    sl.value = String(S.depth);
    q("pchild").disabled = S.depth === 0;
    q("pparent").disabled = S.depth >= S.stack.length - 1;

    const isVar = S.targetMode === "variable";
    for (const x of q("pmode").children) x.setAttribute("aria-pressed", String(x.dataset.mode === S.targetMode));
    q("psel-row").hidden = isVar;
    q("pprop-row").hidden = isVar;
    q("pvar-row").hidden = !isVar;
    q("pscope-row").hidden = !isVar;
    q("pextra").disabled = isVar;
    q("phide").disabled = isVar;

    /* Selects are rebuilt only when the target element actually changed, so a
     * selection made inside them is never clobbered by an unrelated refresh. */
    if (changed) {
      const cands = candidates(t);
      const fill = (node, options, keep) => {
        node.textContent = "";
        for (const o of options) node.append(el("option", o));
        if (keep && [...node.options].some((o) => o.value === keep)) node.value = keep;
      };
      fill(q("psel"), cands.map((c) => ({
        value: c.sel, text: `${c.sel}   — ${c.count} match${c.count === 1 ? "" : "es"}`,
      })), q("psel").value);
      fill(q("pvar"), S.elementVars.map((v) => ({ value: v.name, text: `${v.name}  =  ${v.value}` })), q("pvar").value);
      fill(q("pscope"), [
        { value: ROOT_ARMOR, text: ":root  (whole page)" },
        ...cands.map((c) => ({ value: c.sel, text: `${c.sel}  (${c.count})` })),
      ], q("pscope").value);
    }

    for (const x of q("pseg").children) x.setAttribute("aria-pressed", String(x.dataset.group === S.group));
    q("pextra").textContent = GROUPS[S.group].extra.label;

    /* existing rules for this element → one click to edit */
    const chips = q("pexist");
    chips.textContent = "";
    const touching = rulesTouching(t);
    if (touching.length) {
      chips.append(el("span", { class: "cap", text: "already themed here — click to edit:" }));
      for (const r of touching) {
        const tok = tokenOf(r.decl);
        const chip = el("button", { class: "chip", type: "button", title: ruleCss(r), onclick: () => openEdit(r) },
          el("i", { class: "dot", style: { background: tok ? `var(--${tok}, transparent)` : "transparent" } }),
          el("span", { class: "lab", text: r.meta || ruleCss(r) }));
        chip.addEventListener("pointerenter", () => Preview.show(previewForKey(r.key, r.sel, r.decl, "")));
        chip.addEventListener("pointerleave", () => pickPreview(null));
        chips.append(chip);
      }
    }

    /* palette: tick whatever is currently applied for this selector+property */
    const activeKey = isVar
      ? varKey(q("pscope").value || ROOT_ARMOR, q("pvar").value)
      : selKey(q("psel").value, S.group);
    pickGrid?.setActive(tokenOf(S.rules.find((r) => r.key === activeKey)?.decl));
    pickPreview(null);
  }

  function applySel(decl, meta, group) {
    const sel = selected();
    if (!validSelector(sel)) { flash("invalid selector", "err"); return; }
    if (group === "display" && /^(html|body)$/i.test(sel.trim())) {
      flash("refusing to hide the whole page", "err");
      return;
    }
    upsert({ sel, decl, meta, key: selKey(sel, group) });
    flash(`✓ ${meta}`);
  }

  /* ---- edit panel ---- */
  let editGrid = null;
  const currentEdit = () => S.rules.find((r) => r.key === S.editKey) ?? null;

  function editPreviewSpec(token) {
    const r = currentEdit();
    if (!r) return null;
    /* The selector box may hold an unsaved edit — preview what the user sees. */
    const sel = r.raw !== undefined ? "" : (q("esel")?.value.trim() || r.sel);
    return previewForKey(r.key, sel, r.decl, token);
  }

  function openEdit(rule) {
    const live = S.rules.find((r) => r.key === rule.key) ?? rule;
    dropPanel();
    panelKind = "edit";
    S.editKey = live.key;
    S.locked = true;
    panel = el("section", { class: "panel dlg", role: "dialog", "aria-label": "Edit rule", tabindex: "-1" });
    panel.innerHTML = EDIT_HTML;
    placePanel(panel);
    root.append(panel);
    drag(panel, q("ehead"), rememberPos);

    previewOf = editPreviewSpec;
    editGrid = PaletteGrid({
      onHover: (token) => Preview.show(previewOf(token)),
      onPick: (token) => editPick(token),
    });
    q("egrid").append(editGrid.el);

    q("eclose").addEventListener("click", closePanel);
    q("edone").addEventListener("click", closePanel);
    q("eghost").addEventListener("click", (e) =>
      e.currentTarget.setAttribute("aria-pressed", String(panel.classList.toggle("ghost"))));
    q("edelete").addEventListener("click", () => { removeRule(S.editKey); closePanel(); });
    q("esel").addEventListener("change", commitSelector);
    q("esel").addEventListener("input", () => Preview.show(previewOf("")));
    q("eapply").addEventListener("click", commitDecl);
    q("ecustom").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commitDecl(); }
    });
    q("eraw").addEventListener("change", commitRaw);
    q("eseg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-group]");
      const r = currentEdit();
      if (!b || !r) return;
      const k = decodeKey(r.key);
      if (k.kind !== "sel") return;
      const token = tokenOf(r.decl) || "primary";
      writeRule(r.key, {
        sel: r.sel, decl: declFor(b.dataset.group, token),
        meta: `${b.dataset.group}: ${token}`, key: selKey(r.sel, b.dataset.group),
      });
      flash(`✓ ${b.dataset.group}`);
    });

    drawMask();
    refreshEdit();
    /* Preview the rule's own outline immediately so the user sees the target. */
    Preview.show(previewOf(""));
    panel.focus({ preventScroll: true });
  }

  function editPick(token) {
    const r = currentEdit();
    if (!r) return;
    const k = decodeKey(r.key);
    if (k.kind === "var") {
      writeRule(r.key, {
        sel: r.sel, decl: `${k.name}: var(--${token}) !important;`,
        meta: `var ${k.name} → ${token}`, key: r.key,
      });
      flash(`✓ ${k.name} → ${token}`);
      return;
    }
    if (k.kind !== "sel") return;
    if (k.group?.startsWith("custom:") || k.group === "display") {
      const swapped = String(r.decl).replaceAll(/var\(\s*--[a-z0-9_]+/gi, `var(--${token}`);
      if (swapped === r.decl) { flash("this rule has no colour to change", "warn"); return; }
      writeRule(r.key, { ...r, decl: swapped, meta: `${k.group}: ${token}` });
      flash(`✓ ${token}`);
      return;
    }
    const group = colourGroup(k.group);
    writeRule(r.key, {
      sel: r.sel, decl: declFor(group, token),
      meta: `${group}: ${token}`, key: selKey(r.sel, group),
    });
    flash(`✓ ${group}: ${token}`);
  }

  function commitSelector() {
    const r = currentEdit();
    if (!r) return;
    const sel = q("esel").value.trim();
    const k = decodeKey(r.key);
    if (!validSelector(sel)) { flash("invalid selector", "err"); q("esel").value = r.sel ?? ""; return; }
    if (sel === r.sel) return;
    const key = k.kind === "var" ? varKey(sel, k.name) : selKey(sel, k.group ?? groupOfDecl(r.decl));
    writeRule(r.key, { ...r, sel, key });
    flash("✓ selector updated");
  }

  function commitDecl() {
    const r = currentEdit();
    if (!r || r.raw !== undefined) return;
    const decl = normaliseDecl(q("ecustom").value);
    if (!decl) { flash("that is not a valid declaration", "err"); return; }
    const k = decodeKey(r.key);
    if (k.kind === "var") {
      const first = propsOf(decl)[0] ?? "";
      const name = first.startsWith("--") ? first : k.name;
      writeRule(r.key, {
        sel: r.sel, decl, meta: `var ${name} → ${tokenOf(decl) || "custom"}`, key: varKey(r.sel, name),
      });
    } else {
      const group = groupOfDecl(decl);
      writeRule(r.key, {
        sel: r.sel, decl, meta: `${group}: ${tokenOf(decl) || "custom"}`, key: selKey(r.sel, group),
      });
    }
    flash("✓ declaration updated");
  }

  function commitRaw() {
    const r = currentEdit();
    if (!r) return;
    const next = parseRule(oneLine(q("eraw").value));
    if (!next) { flash("nothing to save", "err"); return; }
    writeRule(r.key, next);
    flash("✓ rule updated");
  }

  /* Refresh mutates state only — it NEVER rebuilds the palette grid. */
  function refreshEdit() {
    if (panelKind !== "edit") return;
    const r = currentEdit();
    if (!r) { closePanel(); return; }
    const k = decodeKey(r.key);
    const isVar = k.kind === "var";
    const isRaw = r.raw !== undefined;

    q("esel-lbl").textContent = isVar ? "Scope" : "Selector";
    q("esel-row").hidden = isRaw;
    if (!isRaw && q("esel") !== root.activeElement) q("esel").value = r.sel;
    q("evar-row").hidden = !isVar;
    if (isVar) q("evar").textContent = k.name;
    q("eprop-row").hidden = isVar || isRaw;
    q("eraw-row").hidden = !isRaw;
    if (isRaw && q("eraw") !== root.activeElement) q("eraw").value = r.raw;
    q("ecustom-row").hidden = isRaw;
    if (!isRaw && q("ecustom") !== root.activeElement) q("ecustom").value = r.decl;
    q("egrid").hidden = isRaw;

    const group = k.kind === "sel" ? colourGroup(k.group) : "";
    for (const b of q("eseg").children) b.setAttribute("aria-pressed", String(b.dataset.group === group));
    editGrid?.setActive(tokenOf(r.decl));

    q("ehint").textContent = isRaw
      ? "Hand-written rule — edit the CSS and press Tab/Enter to save it."
      : isVar
        ? "Hover or Tab a swatch to preview this variable pointing at another palette colour; click commits. Scope is where the override is declared."
        : k.group?.startsWith("custom:") || k.group === "display"
          ? "Hover a swatch to preview substituting the colour inside this rule; click commits."
          : "Hover or Tab a swatch to preview · click commits · switch Property to convert the rule · the selector is editable.";
  }

  /* ── Rules drawer ──────────────────────────────────────────────────── */
  function toggleDrawer() {
    if (drawer) { drawer.remove(); drawer = null; return; }
    drawer = el("section", { class: "panel drawer", role: "dialog", "aria-label": "Rules for this site" });
    drawer.innerHTML = DRAWER_HTML;
    root.append(drawer);
    drag(drawer, q("rhead"));
    q("rclose").addEventListener("click", toggleDrawer);
    q("rclear").addEventListener("click", () => {
      if (S.rules.length) { snapshot(); S.rules = Object.freeze([]); commit(); }
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
    for (const r of S.rules) {
      const tok = tokenOf(r.decl);
      const open = el("button", { class: "open", type: "button", title: ruleLine(r), onclick: () => openEdit(r) },
        el("i", { class: "dot", style: { background: tok ? `var(--${tok}, transparent)` : "transparent" } }),
        el("span", { class: "sel", text: r.raw !== undefined ? r.raw : r.sel }),
        el("span", { class: "meta", text: r.meta || "manual" }));
      /* Hover here previews the rule — and leaving restores whatever the open
       * panel was previewing, WITHOUT rebuilding any panel DOM. */
      open.addEventListener("pointerenter", () => Preview.show(previewForKey(r.key, r.sel, r.decl, "")));
      open.addEventListener("pointerleave", () => Preview.show(previewOf(null)));
      list.append(el("div", { class: "item" }, open,
        el("button", {
          class: "del x", type: "button", title: "Remove this rule", text: "✕",
          onclick: () => removeRule(r.key),
        })));
    }
  }

  /* ══ Mutation / history / persistence ═══════════════════════════════ */
  function snapshot() {
    S.undo.push(S.rules);                       /* frozen array — safe by value */
    if (S.undo.length > 100) S.undo.shift();
    S.redo = [];
  }
  const undo = () => { if (S.undo.length) { S.redo.push(S.rules); S.rules = S.undo.pop(); commit(); } };
  const redo = () => { if (S.redo.length) { S.undo.push(S.rules); S.rules = S.redo.pop(); commit(); } };

  function commit() {
    S.generation++;
    renderLive();
    refreshBar();
    refreshDrawer();
    refreshPanel();
    schedulePersist();
  }

  function validRule(rule) {
    if (rule.raw !== undefined) return rule.raw.length <= LIMITS.DECL;
    if (!validSelector(rule.sel)) { flash("invalid selector", "err"); return false; }
    if (!rule.decl || rule.decl.length > LIMITS.DECL) { flash("declaration too long", "err"); return false; }
    if (decodeKey(rule.key).kind === "invalid") { flash("internal: bad rule key", "err"); return false; }
    return true;
  }

  function upsert(rule) {
    if (!validRule(rule)) return;
    const i = S.rules.findIndex((r) => r.key === rule.key);
    if (i < 0 && S.rules.length >= LIMITS.RULES) { flash(`rule limit (${LIMITS.RULES}) reached`, "err"); return; }
    snapshot();
    const next = S.rules.slice();
    if (i >= 0) next[i] = rule; else next.push(rule);
    S.rules = Object.freeze(next);
    commit();
  }

  /* Replace oldKey in place, even when the new rule has a different key. */
  function writeRule(oldKey, rule) {
    if (!validRule(rule)) return;
    snapshot();
    const next = S.rules.slice();
    if (rule.key !== oldKey) {
      const dup = next.findIndex((r) => r.key === rule.key);
      if (dup >= 0) next.splice(dup, 1);
    }
    const at = next.findIndex((r) => r.key === oldKey);
    if (at >= 0) next[at] = rule; else next.push(rule);
    S.rules = Object.freeze(next);
    S.editKey = rule.key;
    commit();
  }

  function removeRule(key) {
    const i = S.rules.findIndex((r) => r.key === key);
    if (i < 0) return;
    snapshot();
    const next = S.rules.slice();
    next.splice(i, 1);
    S.rules = Object.freeze(next);
    commit();
  }

  const send = (msg) => browser.runtime.sendMessage({ ...msg, origin: ORIGIN })
    .catch((e) => ({ ok: false, error: String(e?.message ?? e) }));

  /* Keep local rules, adopt anything new that appeared on disk. */
  function mergeForeign(foreignPicks) {
    const mine = new Map(S.rules.map((r) => [r.key, r]));
    const merged = [];
    for (const r of parseLines(foreignPicks)) {
      if (mine.has(r.key)) { merged.push(mine.get(r.key)); mine.delete(r.key); }
      else merged.push(r);
    }
    merged.push(...mine.values());
    S.rules = Object.freeze(merged);
  }

  let saveInFlight = null;

  function schedulePersist() {
    if (!S.hydrated) {                          /* never write what we never read */
      setState(`⚠ NOT SAVING — ${S.note || "host unreachable"} · press ⟲`, "err");
      return;
    }
    if (saveInFlight) return;                   /* generation loop picks it up */
    saveInFlight = (async () => {
      try {
        let written = -1;
        while (written !== S.generation) {
          const generation = S.generation;
          await persistOnce();
          written = generation;
        }
      } finally { saveInFlight = null; }
    })();
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function persistOnce() {
    const body = serialise();
    if (body.length > LIMITS.BODY) {
      S.note = "picks region exceeds 512 KiB — remove some rules";
      setState(`⚠ NOT SAVED: ${S.note}`, "err");
      return;
    }
    setState("saving…", "");
    for (let attempt = 0; attempt < 3; attempt++) {
      const reply = await send({ type: "splice", region: "picks", body: serialise(), base_rev: S.rev });
      if (reply?.ok) {
        S.rev = reply.rev ?? 0;
        S.note = "";
        flash(`✓ saved ${String(reply.path ?? "").split("/").pop()}`);
        return;
      }
      if (!reply?.conflict) {
        S.note = reply?.error ?? "no reply";
        setState(`⚠ NOT SAVED: ${S.note}`, "err");
        return;
      }
      /* Someone else wrote the file: adopt their rules, keep ours, retry. */
      const fresh = await send({ type: "read" });
      if (fresh?.ok) {
        S.rev = fresh.rev ?? 0;
        mergeForeign(fresh.picks);
        renderLive(); refreshBar(); refreshDrawer(); refreshPanel();
      }
      await sleep(40 + Math.random() * 120 * (attempt + 1));
    }
    S.note = "the file keeps changing on disk";
    setState(`⚠ NOT SAVED: ${S.note} — press ⟲`, "err");
  }

  async function hydrate(force = false) {
    if (S.hydrated && !force) return true;
    const reply = await send({ type: "read" });
    if (!reply?.ok) {
      S.note = reply?.error ?? "cannot reach the native host";
      return false;
    }
    S.hydrated = true;
    S.note = "";
    S.rev = reply.rev ?? 0;
    S.warnings = reply.warnings ?? [];
    S.rules = Object.freeze(parseLines(reply.picks));
    return true;
  }

  /* Re-read disk and re-apply anything we have locally that disk lacks. */
  async function recover(manual = false) {
    await saveInFlight?.catch(() => {});
    const local = S.rules;
    const before = serialise();
    if (!await hydrate(true)) { baseState(); return false; }
    const merged = S.rules.slice();
    for (const r of local) {
      const i = merged.findIndex((x) => x.key === r.key);
      if (i >= 0) merged[i] = r; else merged.push(r);
    }
    S.rules = Object.freeze(merged);
    renderLive(); refreshBar(); refreshDrawer(); refreshPanel();
    if (serialise() !== before) { S.generation++; schedulePersist(); }
    if (manual) flash("⟲ resynced with disk");
    return true;
  }

  /* Disk changed under us (popup saved / deleted): disk wins. */
  async function rehydrate() {
    await saveInFlight?.catch(() => {});
    const before = S.rules;
    const beforeText = serialise();
    if (!await hydrate(true)) { baseState(); return; }
    if (serialise() !== beforeText) S.undo.push(before);
    renderLive(); refreshBar(); refreshDrawer(); refreshPanel();
    flash("↻ reloaded from disk");
  }

  /* ══ Targeting ══════════════════════════════════════════════════════ */
  function setStack(elm) {
    const chain = [];
    for (let n = elm; n?.nodeType === 1; n = n.parentElement) chain.push(n);
    S.stack = chain;
    S.depth = 0;
    retarget();
  }
  function retarget() {
    drawMask();
    refreshBar();
    if (panelKind === "pick") {
      S.elementVars = getElementVars(target());
      q("pvarbtn").disabled = S.elementVars.length === 0;
      if (!S.elementVars.length) S.targetMode = "selector";
      refreshPick(true);
    }
  }
  function step(delta) {
    if (!S.stack.length) return;
    S.depth = Math.min(Math.max(0, S.depth + delta), S.stack.length - 1);
    retarget();
  }
  function typing() {
    const a = root.activeElement ?? document.activeElement;
    return !!a && (a.isContentEditable || /^(input|select|textarea)$/i.test(a.tagName));
  }

  /* ══ Page events ════════════════════════════════════════════════════ */
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
    const sameTarget = panelKind === "pick" && S.stack.includes(e.target);

    if (e.shiftKey) {
      /* Honour the panel's selector + depth when it is open on this element. */
      if (!sameTarget) { S.locked = false; setStack(e.target); }
      const sel = sameTarget ? selected() : (candidates(target()).at(0)?.sel ?? "");
      if (!validSelector(sel)) { flash("no usable selector here", "err"); return; }
      if (/^(html|body)$/i.test(sel.trim())) { flash("refusing to hide the whole page", "err"); return; }
      upsert({ sel, decl: "display: none !important;", meta: "hidden", key: selKey(sel, "display") });
      flash(`✓ hidden ${sel}`);
      return;
    }
    if (panelKind === "edit") closePanel();
    S.locked = false;
    setStack(e.target);
    openPick();
  }

  function onKey(e) {
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    if (k === "Escape") {
      /* First Esc leaves the field (keeping what you typed), second closes. */
      if (typing()) (root.activeElement ?? document.activeElement)?.blur?.();
      else if (panel) closePanel();
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
      dropIndex();
      await hydrate(true);
      document.documentElement.append(hostEl);
      buildBar();
      renderLive();
      listenerCtl = new AbortController();
      const { signal } = listenerCtl;
      const opts = { capture: true, signal };
      for (const [type, fn] of LISTENERS) window.addEventListener(type, fn, opts);
      window.addEventListener("scroll", scheduleMask, { capture: true, passive: true, signal });
      window.addEventListener("resize", scheduleMask, { passive: true, signal });
      /* SPA route changes leave the stack pointing at detached nodes. */
      globalThis.navigation?.addEventListener("navigate", () => {
        S.stack = []; S.depth = 0; dropIndex(); closePanel();
      }, { signal });
    } else {
      closePanel();
      if (drawer) toggleDrawer();
      bar?.remove();
      bar = null;
      listenerCtl?.abort();
      listenerCtl = null;
      S.stack = [];
      S.depth = 0;
      S.locked = false;
      dropIndex();
      hostEl.remove();
      dropProbe();
      await saveInFlight?.catch(() => {});
      detachSheet();
    }
  }

  /* ══ Extension messages ═════════════════════════════════════════════ */
  browser.runtime.onMessage.addListener((msg) => {
    switch (msg?.type) {
      case "ping":
        return Promise.resolve({ ok: true, active: S.active, rules: S.rules.length, hydrated: S.hydrated });
      case "scan":
        try { return Promise.resolve(scan()); }
        catch (e) { return Promise.resolve({ ok: false, error: `Scan failed: ${e?.message ?? e}` }); }
      case "picker":
        return setActive(msg.enable ?? !S.active).then(() => ({ ok: true, active: S.active }));
      case "reset":
        S.rules = Object.freeze([]); S.undo = []; S.redo = [];
        S.hydrated = true; S.note = ""; S.rev = 0;
        renderLive(); refreshBar(); refreshDrawer(); refreshPanel(); baseState();
        return Promise.resolve({ ok: true });
      case "rehydrate":
        if (!S.active) { S.hydrated = false; return Promise.resolve({ ok: true, active: false }); }
        return rehydrate().then(() => ({ ok: true, rules: S.rules.length }));
      default:
        return false;
    }
  });
})();
