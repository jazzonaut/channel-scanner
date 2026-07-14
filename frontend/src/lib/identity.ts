// Anonymous, persistent client identity stored in localStorage.

const CLIENT_ID_KEY = 'rtlsdr.client_id';
const DISPLAY_NAME_KEY = 'rtlsdr.display_name';

function randomId(): string {
  // Prefer crypto.randomUUID where available; fall back for older/jsdom envs.
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === 'function') {
    return `anon-${c.randomUUID()}`;
  }
  return `anon-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function getOrCreateClientId(): string {
  try {
    const existing = localStorage.getItem(CLIENT_ID_KEY);
    if (existing) return existing;
    const id = randomId();
    localStorage.setItem(CLIENT_ID_KEY, id);
    return id;
  } catch {
    // localStorage unavailable (private mode / SSR); fall back to ephemeral id.
    return randomId();
  }
}

export function getDisplayName(): string | undefined {
  try {
    return localStorage.getItem(DISPLAY_NAME_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

export function setDisplayName(name: string): void {
  try {
    if (name.trim()) localStorage.setItem(DISPLAY_NAME_KEY, name.trim());
    else localStorage.removeItem(DISPLAY_NAME_KEY);
  } catch {
    // ignore persistence failure
  }
}
