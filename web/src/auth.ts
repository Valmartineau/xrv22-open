// Etape 5 — Recuperation et stockage du token d'auth.
//
// Source de verite : le QR code affiche par le serveur Pi (logs +
// futur ecran tactile) contient une URL `http://<pi>/?token=<xxx>`.
// Au premier chargement, on extrait le token de l'URL, on le stocke
// en localStorage et on nettoie l'URL pour ne pas le laisser visible.

const KEY = "xrv22.token";

function readFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search);
  const t = params.get("token");
  if (!t) return null;
  // Nettoie l'URL (sans recharger la page) pour ne pas exposer le token
  // dans la barre d'adresse / historique / partage de capture d'ecran.
  params.delete("token");
  const qs = params.toString();
  const newUrl =
    window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash;
  window.history.replaceState({}, "", newUrl);
  return t;
}

export function getToken(): string | null {
  const fromUrl = readFromUrl();
  if (fromUrl) {
    try {
      localStorage.setItem(KEY, fromUrl);
    } catch {
      /* localStorage indisponible (private mode) — token live uniquement */
    }
    return fromUrl;
  }
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* no-op */
  }
}

// Wrapper fetch qui ajoute Authorization: Bearer <token> automatiquement.
// Si le serveur repond 401, on purge le token local et on recharge -> l'user
// devra rescanner le QR.
export async function authFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    // Pas de reload immediate ici : laisser App.tsx afficher l'ecran token
  }
  return res;
}
