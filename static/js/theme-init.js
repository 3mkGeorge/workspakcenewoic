// Applies the browser's saved theme before first paint (no light/dark flash).
try {
  const theme = localStorage.getItem("storepro-theme");
  if (theme === "dark" || theme === "light") document.documentElement.dataset.bsTheme = theme;
} catch {}
