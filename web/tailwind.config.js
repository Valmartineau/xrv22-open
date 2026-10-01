/** @type {import('tailwindcss').Config} */
// Palette stricte de xrv22/theme/theme.py (SSOT design).
// Toute couleur ajoutee ici doit refleter une constante du theme Python.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Backgrounds
        bg_deep:    "#161820",
        bg:         "#1e2130",
        surface:    "#252836",
        surface_hi: "#2c303e",
        sidebar:    "#181b27",
        // Borders
        sh_d:       "#111318",
        sh_l:       "#363a4e",
        border:     "#2a2e40",
        border_med: "#323648",
        border_hi:  "#3a3e52",
        // Magenta (primary)
        mag:        "#80276c",
        mag2:       "#934a7f",
        mag3:       "#a06a8f",
        mag4:       "#b48aa5",
        mag_dim:    "#2e0e26",
        mag_dim2:   "#4a1840",
        // Amber (secondary)
        amb:        "#f6a117",
        amb2:       "#e6b54a",
        amb3:       "#edc57b",
        amb4:       "#f3d9a4",
        amb_dim:    "#3e2204",
        amb_dim2:   "#5c3208",
        // Semantic
        ok:         "#4ade80",
        ok_dim:     "#0f2d1a",
        err:        "#f43f5e",
        err_deep:   "#7f1d2e",
        err_dim:    "#3a0a14",
        info:       "#38bdf8",
        // Text
        text:       "#e6e6e6",
        text_med:   "#8a8f98",
        text_dim:   "#3e4255",
        text_label: "#6a6e7e",
      },
      fontFamily: {
        // FONT_UI = "DIN Alternate" (UI standard)
        ui:      ['"DIN Alternate"', "system-ui", "sans-serif"],
        // FONT_DISPLAY = "Avenir Next Condensed" (titres)
        display: ['"Avenir Next Condensed"', "Inter", "sans-serif"],
        // FONT_MONO = "Geist Mono"
        mono:    ['"Geist Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        // F_DISPLAY 28, F_TITLE 20, F_SECTION 15, F_LABEL 14, F_CONTROL 13, F_CAPTION 11, F_BADGE 10
        display:  ["28px", { lineHeight: "1.1", fontWeight: "700" }],
        title:    ["20px", { lineHeight: "1.2", fontWeight: "700" }],
        section:  ["15px", { lineHeight: "1.3", fontWeight: "700" }],
        label:    ["14px", { lineHeight: "1.4" }],
        control:  ["13px", { lineHeight: "1.4" }],
        caption:  ["11px", { lineHeight: "1.4" }],
        badge:    ["10px", { lineHeight: "1.2", fontWeight: "700" }],
        mono_xl:  ["19px", { lineHeight: "1.2", fontWeight: "700" }],
        mono_lg:  ["15px", { lineHeight: "1.2", fontWeight: "700" }],
        mono_md:  ["13px", { lineHeight: "1.2" }],
        mono_sm:  ["11px", { lineHeight: "1.2" }],
      },
      spacing: {
        // PAD_XS 4, PAD_SM 8, PAD_MD 14, PAD_LG 20, PAD_XL 28
        pxs: "4px",
        psm: "8px",
        pmd: "14px",
        plg: "20px",
        pxl: "28px",
        // SIDEBAR_W=252 (sidebar.py), TOPBAR_H=58 (theme.py mais 52 dans main_window), STATUSBAR_H=40
        sidebar_w: "252px",
        topbar_h: "52px",
        statusbar_h: "40px",
      },
      borderRadius: {
        // RADIUS_XS 6, SM 10, MD 14, LG 20, PILL 24
        xs: "6px",
        sm: "10px",
        md: "14px",
        lg: "20px",
        pill: "24px",
      },
    },
  },
  plugins: [],
};
