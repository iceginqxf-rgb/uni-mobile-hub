import { ref } from "vue";

// 5 Termix-inspired preset themes, persisted in localStorage (`ios-remote-theme`)
// and applied via <html data-theme="...">.
export const THEME_PRESETS = [
  { id: "dark", isLight: false, bg: "#09090b", panel: "#111114", accent: "#3b82f6" },
  { id: "light", isLight: true, bg: "#fafafa", panel: "#ffffff", accent: "#2563eb" },
  { id: "tokyo-night", isLight: false, bg: "#1a1b26", panel: "#24283b", accent: "#7aa2f7" },
  { id: "nord", isLight: false, bg: "#242933", panel: "#2e3440", accent: "#88c0d0" },
  { id: "dracula", isLight: false, bg: "#282a36", panel: "#303341", accent: "#bd93f9" },
];

const THEME_IDS = THEME_PRESETS.map((p) => p.id);
const KEY = "ios-remote-theme";
const LAST_DARK_KEY = "ios-remote-last-dark";

function _read(key = KEY) {
  try {
    const v = window.localStorage.getItem(key);
    return THEME_IDS.includes(v) ? v : null;
  } catch {
    return null;
  }
}

function _detect() {
  const saved = _read();
  if (saved) return saved;
  try {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

const theme = ref(_detect());

function _apply(value, persist = true) {
  const resolved = THEME_IDS.includes(value) ? value : "dark";
  theme.value = resolved;
  document.documentElement.dataset.theme = resolved;
  if (persist) {
    try {
      window.localStorage.setItem(KEY, resolved);
      if (resolved !== "light") {
        window.localStorage.setItem(LAST_DARK_KEY, resolved);
      }
    } catch {
      /* ignore */
    }
  }
}

_apply(theme.value, false);

export function useTheme() {
  function setTheme(v) {
    _apply(v, true);
  }
  function toggleTheme() {
    if (theme.value === "light") {
      const prevDark = _read(LAST_DARK_KEY);
      _apply(prevDark && prevDark !== "light" ? prevDark : "dark", true);
    } else {
      _apply("light", true);
    }
  }
  return { theme, themes: THEME_PRESETS, setTheme, toggleTheme };
}
