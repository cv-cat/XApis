const pages = new Set(["home", "mine", "explore", "jobs", "articles", "messages", "sources", "rules", "accounts", "settings", "tools", "maintenance", "keywords"]);

export function postId(value) {
  const text = String(value || "").trim();
  if (/^\d{1,30}$/.test(text)) return text;
  try {
    const url = new URL(text);
    if (!["x.com", "www.x.com", "twitter.com", "www.twitter.com"].includes(url.hostname)) return null;
    return url.pathname.match(/\/status\/(\d{1,30})(?:\/|$)/)?.[1] || null;
  } catch { return null; }
}

export function readRoute(hash) {
  const [path, query = ""] = String(hash).replace(/^#/, "").split("?");
  if (/^post\/\d{1,30}$/.test(path)) return {page: "post", detailId: path.slice(5)};
  const page = pages.has(path) ? path : "home";
  if (page !== "explore") return {page};
  const params = new URLSearchParams(query);
  return {page, query: params.get("q") || "", searchKind: params.get("kind") === "user" ? "user" : "search",
    product: ["Latest", "Top", "People", "Media", "Lists"].includes(params.get("product")) ? params.get("product") : "Latest"};
}

export function routeHash(page, state) {
  if (page === "post") return `post/${postId(state.detailId) || ""}`;
  if (page !== "explore") return page;
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.searchKind === "user") params.set("kind", "user");
  if (state.product && state.product !== "Latest") params.set("product", state.product);
  return "explore" + (params.size ? "?" + params : "");
}

export function appendUnique(previous, incoming) {
  const seen = new Set(previous.map((p) => p.work_id));
  return [...previous, ...incoming.filter((p) => !seen.has(p.work_id) && seen.add(p.work_id))];
}
