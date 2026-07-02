// Cloudflare Worker: pośrednik między PWA a GitHub Actions.
// PWA wysyła POST {auth: <hash hasła>}. Worker sprawdza hash (constant-time) i — jeśli pasuje —
// uruchamia workflow_dispatch, używając tokenu GitHuba trzymanego jako SEKRET Workera.
// Dzięki temu token GitHuba NIGDY nie trafia do publicznego kodu strony, a Worker nie zna
// surowego hasła (dostaje tylko jego PBKDF2-hash) — więc nie odszyfruje danych zdrowotnych.
//
// Sekrety (wrangler secret put ...):  GH_TOKEN, REFRESH_AUTH_HASH
// Zmienne (wrangler.toml [vars]):      GH_REPO, GH_WORKFLOW, GH_REF, ALLOW_ORIGIN, REFRESH_DAYS

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOW_ORIGIN || "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
      "Vary": "Origin"
    };
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405, cors);

    let body;
    try { body = await req.json(); }
    catch { return json({ error: "bad_json" }, 400, cors); }

    const auth = String((body && body.auth) || "").toLowerCase();
    const expected = String(env.REFRESH_AUTH_HASH || "").toLowerCase();
    if (!expected) return json({ error: "server_not_configured" }, 500, cors);
    if (!auth || !timingSafeEqual(auth, expected)) return json({ error: "unauthorized" }, 401, cors);

    // Rejestracja powiadomien push: zapisz subskrypcje w repo (push/subscriptions.json).
    if (body && body.sub) return await storeSubscription(env, body.sub, cors);

    const repo = env.GH_REPO;                       // np. "flechow/health"
    const wf = env.GH_WORKFLOW || "update.yml";
    const ref = env.GH_REF || "main";
    const days = env.REFRESH_DAYS || "3";           // szybka ścieżka: pobierz tylko ostatnie N dni i scal

    const gh = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/${wf}/dispatches`,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GH_TOKEN}`,
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "protokol-refresh-worker"
        },
        body: JSON.stringify({ ref, inputs: { days: String(days) } })
      }
    );

    if (gh.status === 204) return json({ ok: true }, 200, cors);
    const detail = (await gh.text()).slice(0, 400);
    return json({ error: "github_dispatch_failed", status: gh.status, detail }, 502, cors);
  }
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "Content-Type": "application/json" }
  });
}

// Zapis/aktualizacja subskrypcji push w pliku repo push/subscriptions.json (upsert po endpoint).
// Wymaga, by GH_TOKEN mial uprawnienie contents:write do repo.
async function storeSubscription(env, sub, cors) {
  const ep = sub && sub.endpoint;
  if (!ep) return json({ error: "bad_sub" }, 400, cors);
  const repo = env.GH_REPO, ref = env.GH_REF || "main", path = "push/subscriptions.json";
  const gh = {
    "Authorization": `Bearer ${env.GH_TOKEN}`,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "protokol-refresh-worker"
  };
  let list = [], sha;
  const get = await fetch(`https://api.github.com/repos/${repo}/contents/${encodeURIComponent(path)}?ref=${ref}`, { headers: gh });
  if (get.status === 200) {
    const j = await get.json();
    sha = j.sha;
    try { const parsed = JSON.parse(atob((j.content || "").replace(/\n/g, ""))); if (Array.isArray(parsed)) list = parsed; } catch (_) {}
  }
  list = list.filter((s) => s && s.endpoint !== ep);
  list.push(sub);
  const content = btoa(unescape(encodeURIComponent(JSON.stringify(list, null, 2))));
  const put = await fetch(`https://api.github.com/repos/${repo}/contents/${encodeURIComponent(path)}`, {
    method: "PUT", headers: gh,
    body: JSON.stringify({ message: "Rejestracja subskrypcji push", content, sha, branch: ref })
  });
  if (put.status === 200 || put.status === 201) return json({ ok: true, count: list.length }, 200, cors);
  const detail = (await put.text()).slice(0, 300);
  return json({ error: "store_failed", status: put.status, detail }, 502, cors);
}

// Porównanie o stałym czasie (nie ujawnia długości dopasowania przez timing).
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
