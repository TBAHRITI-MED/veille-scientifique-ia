// Préférences locales (historique, thème, options) : jamais bloquant si le stockage est indisponible.

export function load<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(`veille:${key}`);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function save(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(`veille:${key}`, JSON.stringify(value));
  } catch {
    /* stockage plein ou désactivé : on continue sans */
  }
}
