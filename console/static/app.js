"use strict";
import {postId, readRoute, routeHash, appendUnique} from "./navigation.mjs";
import {ChatVault} from "./chat-client.mjs";
const paths = {
  home: "M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
  search: "m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  post: "M14 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-9M20 2l2 2-11 11-4 1 1-4Z",
  spark:
    "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4",
  clock: "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  bolt: "m13 2-9 12h7l-1 8 10-13h-7Z",
  users:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.9M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0m4-3.9a4 4 0 0 1 0 7.8",
  user: "M20 21v-2a7 7 0 0 0-14 0v2M16 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  settings:
    "m12 3 2 3 4-1 1 4 3 3-3 2 1 4-4 1-4 3-2-3-4 1-1-4-3-2 3-3-1-4 4 1Zm3 9a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  globe:
    "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0M2 12h20M12 2a18 18 0 0 1 0 20 18 18 0 0 1 0-20",
  mail: "M3 5h18v14H3ZM3 6l9 7 9-7",
  article: "M5 3h14v18H5ZM8 7h8m-8 4h8m-8 4h5",
  image: "M3 3h18v18H3Zm0 14 6-6 5 5 3-3 4 4M8 7h.01",
  heart:
    "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8",
  reply: "M21 11a8 8 0 0 1-8 8H9l-6 3V11a9 9 0 0 1 18 0",
  repost: "m3 8 4-4 4 4M7 4v12h6m8 0-4 4-4-4m4 4V8h-6",
  bookmark: "M6 3h12v18l-6-4-6 4Z",
  chart: "M4 21V11m6 10V3m6 18v-7m6 7V7",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  back: "M19 12H5m5-5-5 5 5 5",
  chevron: "m9 5 7 7-7 7",
  refresh: "M21 3v6h-6M3 21v-6h6M20 9a8 8 0 0 0-14-5M4 15a8 8 0 0 0 14 5",
  plus: "M12 5v14M5 12h14",
  close: "m6 6 12 12M6 18 18 6",
  shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Zm-4 10 3 3 5-6",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  logout: "M9 3H3v18h6m7-14 5 5-5 5M8 12h13",
  link: "M10 13a5 5 0 0 0 7 0l4-4a5 5 0 0 0-7-7l-2 2m2 7a5 5 0 0 0-7 0l-4 4a5 5 0 0 0 7 7l2-2",
  check: "m5 12 4 4L19 6",
  code: "m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
};
const icon = (n) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[n] || paths.post}"/></svg>`;
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const safeURL = (v) => {
  try {
    const u = new URL(v);
    return ["https:", "http:"].includes(u.protocol) ? esc(u.href) : "#";
  } catch {
    return "#";
  }
};
const fmt = (n) =>
  Intl.NumberFormat("zh-CN", {
    notation: Number(n) > 9999 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(Number(n) || 0);
const date = (v) =>
  v
    ? new Date(typeof v === "number" ? v * 1000 : v).toLocaleString("zh-CN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "尚未运行";
const $ = (q, root = document) => root.querySelector(q);
const S = {
  user: null,
  csrf: "",
  accounts: [],
  account: localStorage.getItem("xapis-account") || "",
  page: "home",
  stats: { jobs: {} },
  entries: [],
  sources: [],
  groups: [],
  maintenance: [],
  maintenanceTimer: null,
  chat: null,
  chatVault: null,
  rules: [],
  jobs: [],
  posts: [],
  people: [],
  capabilities: { reads: [] },
  version: 0,
  cursor: null,
  query: "",
  product: "Latest",
  searchKind: "search",
  detailId: "",
  detailPost: null,
  detailContext: [],
  replies: [],
  detailCursor: null,
  route: "",
  jobFilter: "draft",
  modal: null,
};
const titles = {
  home: ["主页", "你的内容，你的节奏。"],
  mine: ["我的贴文", "与你的 X 账号实时同步"],
  explore: ["探索", "发现对话，也发现下一条灵感"],
  post: ["贴文详情", "查看原文与评论"],
  jobs: ["内容工作室", "从灵感到发布，每一步都在这里"],
  articles: ["文章", "写下值得被完整阅读的观点"],
  messages: ["私信", "X Chat 会话与成员"],
  sources: ["热点雷达", "把新鲜资讯，变成你的下一条贴文"],
  rules: ["自动化", "让好内容，在合适的时候发生"],
  accounts: ["账号管理", "一个工作台，连接你的 X 账号"],
  settings: ["设置", "让工作台适合你的工作方式"],
  tools: ["API 工具箱", "访问 XApis 已支持的读取能力"],
  maintenance: ["账号养护", "只读浏览，按节奏积累；权限到期自动释放"],
  keywords: ["关键词目录", "用分组管理定向浏览的关键词"],
};
const navs = [
  ["home", "home", "主页"],
  ["explore", "search", "探索"],
  ["mine", "user", "我的贴文"],
  ["jobs", "post", "内容工作室"],
  ["messages", "mail", "私信"],
  ["sources", "globe", "热点雷达"],
  ["rules", "bolt", "自动化"],
  ["accounts", "users", "账号管理"],
  ["maintenance", "shield", "账号养护"],
  ["keywords", "bookmark", "关键词目录"],
  ["settings", "settings", "设置"],
];
async function api(path, options = {}) {
  const method = options.method || "GET",
    headers = {
      "X-Requested-With": "XApis",
      ...(S.csrf ? { "X-CSRF-Token": S.csrf } : {}),
      ...options.headers,
    };
  let body = options.body;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const res = await fetch("/api" + path, {
    ...options,
    method,
    headers,
    body,
    credentials: "same-origin",
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error("服务暂时不可用，请稍后重试");
  }
  if (!res.ok) {
    if (res.status === 401 && S.user) {
      S.chatVault?.dispose(); S.chatVault = null; S.chat = null;
      S.user = null;
      renderLogin(false);
    }
    const details = data.fields
      ?.map((e) => e.field + ": " + e.message)
      .join("；");
    throw new Error(
      (typeof data.detail === "string" ? data.detail : "请求失败") +
        (details ? " · " + details : ""),
    );
  }
  return data;
}
let toastTimer;
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 5500);
}
function avatar(name, url = "", size = "") {
  return /^https:\/\/([\w-]+\.)?twimg\.com\//.test(url)
    ? `<img class="avatar ${size}" src="${esc(url)}" alt="${esc(name)}的头像" loading="lazy">`
    : `<span class="avatar ${size}" aria-hidden="true">${esc((name || "X").slice(0, 1).toUpperCase())}</span>`;
}
const current = () => S.accounts.find((a) => a.id === S.account);
function badge(text, style = "") {
  return `<span class="badge ${style}">${esc(text)}</span>`;
}
function empty(title, text, ico = "post", button = "", action = "") {
  return `<div class="empty"><div class="empty-icon">${icon(ico)}</div><h2>${esc(title)}</h2><p>${esc(text)}</p>${button ? `<button class="primary" data-action="${action}">${esc(button)} ${icon("arrow")}</button>` : ""}</div>`;
}
function loading() {
  return '<div class="loading"><div class="spinner"></div>正在读取…</div>';
}
function field(
  label,
  name,
  placeholder = "",
  type = "text",
  value = "",
  extra = "",
) {
  return `<div class="field"><label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" placeholder="${esc(placeholder)}" value="${esc(value)}" ${extra}></div>`;
}
function textarea(label, name, value = "", placeholder = "", extra = "") {
  return `<div class="field"><label for="f-${name}">${label}</label><textarea id="f-${name}" name="${name}" placeholder="${esc(placeholder)}" ${extra}>${esc(value)}</textarea></div>`;
}
const errorSlot = () => '<div class="form-error" role="alert"></div>';
function showError(form, error) {
  const el = $(".form-error", form);
  if (el) {
    el.textContent = error.message;
    el.classList.add("show");
    el.scrollIntoView({ block: "nearest" });
  } else toast(error.message);
}
function modal(title, html, context = {}) {
  S.modal = context;
  const el = $("#modal");
  el.innerHTML = `<div class="modal-head"><h2>${esc(title)}</h2><button class="icon-btn" data-action="close" aria-label="关闭">${icon("close")}</button></div><div class="modal-body">${html}</div>`;
  if (!el.open) el.showModal();
  setTimeout(
    () => el.querySelector("input:not([type=hidden]),textarea,select")?.focus(),
    20,
  );
}
function closeModal() {
  if (S.modal?.busy) {
    toast("正在处理，请稍候");
    return;
  }
  $("#modal").close();
  S.modal = null;
}
function renderLogin(setup) {
  $("#app").innerHTML =
    `<main class="login-layout"><section class="login-story"><div class="brand"><img src="/static/mark.svg" alt=""><b>XApis</b><span>CONSOLE</span></div><div class="eyebrow">YOUR VOICE. AMPLIFIED.</div><h1>让灵感发声，<br>让运营<em>更从容。</em></h1><p>把你的 X 账号、内容与 AI 放在一起。<br>从发现热点，到写下观点，再到准时发布。</p><div class="login-feature">${icon("shield")}账号独立代理 ${icon("spark")}AI 内容创作 ${icon("bolt")}自动化工作流</div><div class="login-foot">XAPIS · YOUR SELF-HOSTED WORKSPACE</div></section><section class="login-form-wrap"><form class="login-form" data-form="${setup ? "setup" : "login"}"><h2>${setup ? "创建你的工作台" : "欢迎回来"}</h2><p>${setup ? "第一次见面。创建的首位用户将成为管理员，之后由管理员邀请其他用户。" : "登录你的工作台，继续创作与连接。"}</p>${setup ? field("初始化令牌", "token", "部署时生成的初始化令牌", "password", "", 'required autocomplete="off"') + `<div class="notice small">在部署终端运行：<br><code>docker compose exec web python -m console.manage setup-token</code></div>` : ""}${field("用户名", "username", "输入用户名", "text", "", 'required minlength="3" maxlength="40" autocomplete="username"')}${field("密码", "password", setup ? "至少 12 位字符" : "输入密码", "password", "", 'required minlength="' + (setup ? '12' : '1') + '" maxlength="128" autocomplete="' + (setup ? "new-password" : "current-password") + '"')}${errorSlot()}<button class="primary" type="submit">${setup ? "创建管理员，开始使用" : "登录工作台"} ${icon("arrow")}</button><p class="tiny muted">${setup ? "账号密码仅用于登录此控制台。X 账号会在工作台中单独连接。" : "私有部署 · 凭据加密存储 · 会话安全验证"}</p></form></section></main>`;
}
function shell() {
  const title = titles[S.page] || titles.home;
  $("#app").innerHTML =
    `<div class="shell ${["home", "mine", "explore", "post"].includes(S.page) ? "reading-shell" : "workspace-shell"}"><aside class="sidebar"><a class="brand" href="#home"><img src="/static/mark.svg" alt=""><b>XApis</b><span>CONSOLE</span></a><nav class="nav" aria-label="主要导航">${navs.map(([id, ic, label], i) => `${id === 'jobs' ? '<div class="nav-label">内容运营</div>' : id === 'accounts' ? '<div class="nav-label">账号管理</div>' : ''}<button class="${S.page === id ? "active " : ""}${["mine", "messages", "sources", "rules", "maintenance", "keywords"].includes(id) ? "mobile-hide" : ""}" data-page="${id}" title="${label}" ${S.page === id ? 'aria-current="page"' : ""}>${icon(ic)}<span>${label}</span></button>`).join("")}<button class="mobile-menu" data-action="mobile-menu" aria-label="更多功能">${icon("more")}<span>更多</span></button></nav><button class="primary" data-action="compose" aria-label="创作贴文">${icon("plus")}<span>发布贴文</span></button><div class="sidebar-foot"><button class="user-chip" data-page="settings">${avatar(S.user.username)}<span class="grow"><strong>${esc(S.user.username)}</strong><small>${S.user.role === "admin" ? "管理员" : "团队成员"}</small></span>${icon("more")}</button></div></aside><main class="main" data-current-page="${S.page}"><header class="topbar"><div class="topbar-heading">${S.page === "post" ? `<button class="icon-btn" data-action="back-from-post" aria-label="返回上一页">${icon("back")}</button>` : ""}<div class="topbar-title"><h1>${title[0]}</h1><p>${title[1]}</p></div></div><div class="row topbar-tools">${S.accounts.length ? `<select id="account-switch" aria-label="切换 X 账号">${S.accounts.map((a) => `<option value="${a.id}" ${S.account === a.id ? "selected" : ""}>${esc(a.handle ? "@" + a.handle : a.name)}${a.status !== "connected" ? " · 待登录" : ""}</option>`).join("")}</select>` : `<button class="secondary" data-action="add-account">${icon("plus")}连接账号</button>`}<button class="icon-btn" data-action="refresh" aria-label="刷新页面">${icon("refresh")}</button></div></header><section id="view">${loading()}</section></main><aside class="rightbar"><form class="search-box" data-form="global-search">${icon("search")}<input name="q" placeholder="搜索 X 上的内容" aria-label="搜索 X 上的内容" required></form><div id="widgets"></div><div class="right-footer"><b>XApis 运营工作台</b> · 自主部署<br>让创作更专注，让连接更简单。<br><button class="text-btn" data-page="tools">API 能力</button> · <button class="text-btn" data-page="articles">文章管理</button></div></aside></div>`;
  widgets();
}
function widgets() {
  const el = $("#widgets");
  if (!el) return;
  const a = current(),
    j = S.stats.jobs || {};
  el.innerHTML = `<section class="widget"><div class="head"><h3>运营概览</h3>${a?.status === "connected" ? '<span class="badge"><i class="live-dot"></i>已连接</span>' : badge("等待连接", "gray")}</div><div class="metrics"><div class="metric"><strong>${fmt(j.sent)}</strong><span>已完成内容任务</span></div><div class="metric"><strong>${fmt(j.queued)}</strong><span>等待发布</span></div><div class="metric"><strong>${fmt(j.draft)}</strong><span>创作草稿</span></div><div class="metric"><strong>${fmt(S.stats.rules)}</strong><span>运行中的自动化</span></div></div><div class="widget-note">${a ? `${esc(a.name)}<br>${icon("shield").replace("<svg", '<svg width="13" height="13"')} 账号独立代理 · ${S.capabilities.gateway === "go-tls-client" ? "Go TLS 网关" : "本地传输"}` : "连接第一个账号，开启你的内容工作流。"}</div></section><section class="widget"><div class="head"><h3>热点灵感</h3><button class="text-btn" data-page="sources">查看全部</button></div>${
    S.entries
      .slice(0, 3)
      .map(
        (e, i) =>
          `<button class="trend" data-action="entry-compose" data-id="${e.id}"><span class="label"><span>${String(i + 1).padStart(2, "0")} · ${esc(e.source_name)}</span>${icon("spark")}</span><strong>${esc(e.title)}</strong></button>`,
      )
      .join("") ||
    '<p class="widget-empty">好内容，从好信息开始。<br>添加 AI 网站或 RSS 来源，让最新动态成为你的创作起点。</p><button class="text-btn" data-page="sources">添加热点来源 →</button>'
  }</section><section class="widget"><div class="head"><h3>让创作形成习惯</h3>${icon("bolt")}</div><p class="widget-empty">采集新资讯 → AI 提炼观点 → 审核或自动发布。把重复的事，交给自动化。</p><button class="text-btn" data-page="rules">创建你的工作流 →</button></section>`;
}
async function refreshBase() {
  const [accounts, stats, entries, cap] = await Promise.all([
    api("/accounts"),
    api("/stats"),
    api("/entries"),
    api("/capabilities"),
  ]);
  S.accounts = accounts;
  S.stats = stats;
  S.entries = entries;
  S.capabilities = cap;
  if (!accounts.some((a) => a.id === S.account))
    S.account = accounts[0]?.id || "";
  localStorage.setItem("xapis-account", S.account);
}
async function navigate(page, options = {}) {
  clearTimeout(S.maintenanceTimer);
  if (page !== "messages" || S.chat?.account !== S.account) { S.chatVault?.dispose(); S.chatVault = null; S.chat = null; }
  if (!titles[page]) page = "home";
  if (page === "post" && !postId(S.detailId)) page = "home";
  S.page = page;
  S.cursor = null;
  S.posts = [];
  S.people = [];
  S.version++;
  const version = S.version;
  S.route = routeHash(page, S);
  if (location.hash.slice(1) !== S.route) {
    const state = page === "post" ? {xapisBack: options.back || "#home"} : {};
    if (options.restore) history.replaceState(history.state, "", "#" + S.route);
    else history.pushState(state, "", "#" + S.route);
  }
  window.scrollTo({top: 0, behavior: "instant"});
  shell();
  try {
    const [stats, accounts] = await Promise.all([
      api("/stats"),
      api("/accounts"),
    ]);
    if (version !== S.version) return;
    S.stats = stats;
    S.accounts = accounts;
    await loadPage(version, options);
    if (S.page === "tools") renderExplorerFields();
  } catch (e) {
    if (version === S.version && $("#view"))
      $("#view").innerHTML =
        `<div class="error-box">${esc(e.message)} <button data-action="refresh">重新加载</button></div>`;
  }
  widgets();
}
function navigateRoute(hash) {
  const route = readRoute(hash);
  Object.assign(S, route);
  return navigate(route.page, {restore: true});
}
function openPost(value) {
  const id = postId(value);
  if (!id) throw new Error("请输入有效的 X 贴文链接或数字 ID");
  if (S.page === "post" && S.detailId === id) {
    $("#post-replies")?.scrollIntoView({behavior: "smooth", block: "start"});
    return;
  }
  const back = location.hash || "#home";
  S.detailId = id;
  return navigate("post", {back});
}
function needAccount() {
  const a = current();
  if (a?.status === "connected") return false;
  $("#view").innerHTML = onboarding(a);
  return true;
}
function onboarding(a) {
  return `<div class="onboarding"><div class="eyebrow">WELCOME TO YOUR WORKSPACE</div><h2>${a ? "距离开始，只差一步。" : "你好，你的下一条好内容<br>从这里开始。"}</h2><p>${a ? "账号已添加。通过已绑定的专属代理登录 X，即可查看时间线和发布贴文。" : "连接 X 账号，让 AI 帮你整理灵感、写出观点。把发布计划交给工作台，把时间留给创作。"}</p><div class="steps"><span class="step"><i>1</i>添加账号</span>${icon("chevron")}<span class="step"><i>2</i>绑定代理</span>${icon("chevron")}<span class="step"><i>3</i>登录 X</span></div><button class="primary" data-action="${a ? "login-account" : "add-account"}" ${a ? `data-id="${a.id}"` : ""}>${icon("plus")}${a ? "完成账号登录" : "连接第一个账号"}</button></div><div class="onboarding-note row">${icon("home")}<p>连接后，这里会显示你的 X 时间线。<br><span>也可以先配置 AI 和热点来源，为下一条内容做好准备。</span></p></div><div class="page-pad row wrap onboarding-shortcuts"><button class="secondary" data-page="sources">${icon("globe")}热点雷达</button><button class="secondary" data-page="rules">${icon("bolt")}自动化</button><button class="secondary" data-page="settings">${icon("spark")}连接 AI</button></div>`;
}
function quickComposer() {
  const a = current();
  return `<div class="quick-compose">${avatar(a?.name, a?.avatar)}<div class="grow"><textarea id="quick-text" placeholder="今天，有什么想分享？" aria-label="贴文内容"></textarea><div class="composer-footer"><div class="toolbar"><button class="icon-btn" data-action="compose" title="添加图片或视频">${icon("image")}</button><button class="icon-btn" data-action="compose-schedule" title="定时发布">${icon("clock")}</button><button class="text-btn" data-action="compose-ai">${icon("spark")}AI 帮我写</button></div><button class="primary" data-action="compose">写贴文</button></div><div class="compose-hint">你的表达，AI 助力。发布前随时编辑。</div></div></div>`;
}
function postCard(p, {focal = false} = {}) {
  const own = p.user_id === current()?.x_id;
  return `<article class="feed-card${focal ? " focal-post" : ""}" data-post-id="${esc(p.work_id)}">${avatar(p.nickname, p.avatar)}<div class="grow"><div class="post-heading"><b>${esc(p.nickname || p.screen_name)}</b><span>@${esc(p.screen_name)}</span><span>· ${esc(date(p.create_time))}</span><span class="grow"></span><button class="icon-btn" data-action="post-more" data-id="${esc(p.work_id)}" aria-label="更多贴文操作">${icon("more")}</button></div>${focal ? `<div class="post-text">${esc(p.title)}</div>` : `<a class="post-text post-open" href="#post/${esc(p.work_id)}" data-action="detail" data-id="${esc(p.work_id)}">${esc(p.title)}</a>`}${p.image_urls?.length || p.video_urls?.length ? `<div class="post-media">${(p.image_urls || []).map((u) => `<img src="${safeURL(u)}" alt="贴文配图" loading="lazy">`).join("")}${(p.video_urls || []).map((u) => `<video src="${safeURL(u)}" controls preload="none"></video>`).join("")}</div>` : ""}<div class="post-actions"><button data-action="detail" data-id="${esc(p.work_id)}" title="查看评论" aria-label="查看评论">${icon("reply")}${fmt(p.reply_count)}</button><button class="${p.retweeted ? "chosen" : ""}" ${current()?.policy?.can_write === false ? 'disabled aria-disabled="true"' : ""} data-action="interact" data-type="${p.retweeted ? "unrepost" : "repost"}" data-id="${esc(p.work_id)}" title="${p.retweeted ? "取消转帖" : "转帖"}" aria-label="${p.retweeted ? "取消转帖" : "转帖"}">${icon("repost")}${fmt(p.retweet_count)}</button><button class="${p.liked ? "liked" : ""}" ${current()?.policy?.can_write === false ? 'disabled aria-disabled="true"' : ""} data-action="interact" data-type="${p.liked ? "unlike" : "like"}" data-id="${esc(p.work_id)}" title="${p.liked ? "取消喜欢" : "喜欢"}" aria-label="${p.liked ? "取消喜欢" : "喜欢"}">${icon("heart")}${fmt(p.like_count)}</button><a href="https://x.com/i/status/${esc(p.work_id)}" target="_blank" rel="noopener noreferrer" title="在 X 查看" aria-label="在 X 查看">${icon("chart")}${fmt(p.view_count)}</a><button class="${p.bookmarked ? "chosen" : ""}" ${current()?.policy?.can_write === false ? 'disabled aria-disabled="true"' : ""} data-action="interact" data-type="${p.bookmarked ? "unbookmark" : "bookmark"}" data-id="${esc(p.work_id)}" title="${p.bookmarked ? "移除书签" : "添加书签"}" aria-label="${p.bookmarked ? "移除书签" : "添加书签"}">${icon("bookmark")}</button></div></div></article>`;
}
async function loadFeed(version, kind = "home", append = false, q = "") {
  const params = new URLSearchParams({ kind, q, product: S.product });
  if (append && S.cursor) params.set("cursor", S.cursor);
  const data = await api(`/accounts/${S.account}/timeline?` + params);
  if (version !== S.version) return;
  S.cursor = append && data.cursor === S.cursor ? null : data.cursor;
  const people =
    kind === "search" && S.product === "People" ? data.users || [] : [];
  S.people = append
    ? [
        ...S.people,
        ...people.filter((p) => !S.people.some((x) => x.x_id === p.x_id)),
      ]
    : people;
  S.posts = append
    ? [
        ...S.posts,
        ...data.posts.filter(
          (p) => !S.posts.some((x) => x.work_id === p.work_id),
        ),
      ]
    : data.posts;
  const el = $("#feed");
  if (!el) return;
  el.innerHTML =
    (data.profile ? profileCard(data.profile) : "") +
    S.people.map(profileCard).join("") +
    S.posts.map(postCard).join("") +
    (!S.posts.length && !S.people.length
      ? empty(
          "这里暂时安静",
          "暂无可显示的贴文，可以刷新或试试其他关键词。",
          "post",
        )
      : "") +
    (S.cursor
      ? '<button class="secondary load-more" data-action="load-more">加载更多</button>'
      : "");
}
function profileCard(p) {
  return `<div class="card"><div class="row">${avatar(p.name, p.avatar)}<div class="grow"><h3>${esc(p.name)}</h3><span class="muted small">@${esc(p.handle)}</span></div><button class="secondary" ${current()?.policy?.can_write === false ? 'disabled aria-disabled="true"' : ""} data-action="interact" data-type="${p.followed ? "unfollow" : "follow"}" data-id="${esc(p.x_id)}">${p.followed ? "取消关注" : "关注"}</button></div><p>${esc(p.bio)}</p><div class="job-meta">${fmt(p.followers)} 关注者 · ${fmt(p.following)} 正在关注</div></div>`;
}
async function loadPost(version, append = false) {
  const cursor = append ? S.detailCursor : null;
  if (append && !cursor) return;
  const suffix = cursor ? "?" + new URLSearchParams({cursor}) : "";
  const data = await api(`/accounts/${S.account}/posts/${S.detailId}` + suffix);
  if (version !== S.version) return;
  S.detailPost = data.post || S.detailPost;
  if (!append) S.detailContext = data.context || [];
  S.replies = appendUnique(append ? S.replies : [], data.replies || []);
  S.detailCursor = append && data.cursor === cursor ? null : data.cursor;
  S.posts = [...S.detailContext, ...(S.detailPost ? [S.detailPost] : []), ...S.replies];
  const canReply = current()?.policy?.can_write !== false;
  $("#post-content").innerHTML = `${S.detailContext.length ? `<section class="thread-context" aria-label="对话上文"><div class="section-label">对话上文</div>${S.detailContext.map((p) => postCard(p)).join("")}</section>` : ""}${S.detailPost ? postCard(S.detailPost, {focal: true}) : `<div class="page-pad"><div class="notice">X 暂未返回这条贴文的原文，可能受可见性限制。<a href="https://x.com/i/status/${S.detailId}" target="_blank" rel="noopener noreferrer">在 X 查看</a></div></div>`}<section id="post-replies" aria-labelledby="replies-heading"><div class="replies-heading"><div><h2 id="replies-heading">评论</h2><p>${S.replies.length ? `已加载 ${S.replies.length} 条回复` : "这条贴文下的对话"}</p></div>${S.detailPost ? `<button class="secondary" data-action="reply" data-id="${S.detailId}" ${canReply ? "" : 'disabled title="账号处于只读养护期"'}>${icon("reply")}${canReply ? "回复这条贴文" : "养护期仅浏览"}</button>` : ""}</div><div id="replies-list">${S.replies.map((p) => postCard(p)).join("") || empty("暂无可显示的评论", S.detailCursor ? "可以继续加载，查看 X 返回的后续评论。" : "X 当前没有返回可见评论。", "reply")}</div>${S.detailCursor ? '<button class="secondary load-more" data-action="load-comments">加载更多评论</button>' : S.replies.length ? '<p class="feed-end">已显示当前可读取的评论</p>' : ""}</section>`;
}
async function loadPage(version) {
  const view = $("#view");
  if (S.page === "post") {
    if (needAccount()) return;
    S.detailPost = null;
    S.detailContext = [];
    S.replies = [];
    S.detailCursor = null;
    view.innerHTML = `<div id="post-content">${loading()}</div>`;
    return loadPost(version);
  }
  if (["maintenance", "keywords"].includes(S.page)) {
    const [groups, tasks] = await Promise.all([
      api("/keyword-groups"),
      api("/maintenance"),
    ]);
    if (version !== S.version) return;
    S.groups = groups;
    S.maintenance = tasks;
    view.innerHTML = S.page === "keywords" ? keywordsPage() : maintenancePage();
    if (S.page === "maintenance") startMaintenanceRefresh(version);
    return;
  }
  if (["home", "mine"].includes(S.page)) {
    if (needAccount()) return;
    view.innerHTML = `<div class="tabs"><button data-page="home" class="${S.page === "home" ? "active" : ""}">时间线</button><button data-page="mine" class="${S.page === "mine" ? "active" : ""}">我的贴文</button></div>${S.page === "home" ? quickComposer() : ""}<div class="section-label"><span>${S.page === "home" ? "来自你的 X 时间线" : "我的公开内容"}</span><span>实时连接 X</span></div><div id="feed">${loading()}</div>`;
    return loadFeed(version, S.page === "mine" ? "mine" : "home");
  }
  if (S.page === "explore") {
    if (needAccount()) return;
    view.innerHTML = `<div class="search-page"><form data-form="search"><div class="search-box"><label class="sr-only" for="search-query">搜索内容</label>${icon("search")}<input id="search-query" name="q" placeholder="搜索关键词、@用户名或贴文链接" value="${esc(S.query)}" required><button class="primary search-submit" type="submit">搜索</button></div><div class="search-filters"><div class="field"><label for="search-kind">查找范围</label><select id="search-kind" name="kind"><option value="search" ${S.searchKind === "search" ? "selected" : ""}>搜索贴文</option><option value="user" ${S.searchKind === "user" ? "selected" : ""}>用户主页</option><option value="detail">打开贴文链接 / ID</option></select></div><div class="field"><label for="search-product">结果类型</label><select id="search-product" name="product" ${S.searchKind === "user" ? "disabled" : ""}>${[["Latest", "最新"], ["Top", "热门"], ["People", "用户"], ["Media", "媒体"], ["Lists", "列表"]].map(([value, label]) => `<option value="${value}" ${S.product === value ? "selected" : ""}>${label}</option>`).join("")}</select></div></div></form></div>${S.query ? `<div class="section-label"><span>${S.searchKind === "user" ? "用户主页" : "搜索结果"} · ${esc(S.query)}</span></div>` : ""}<div id="feed">${S.query ? loading() : empty("从一个好问题开始", "搜索 X 上的贴文、用户与对话，找到你的下一条创作灵感。", "search")}</div>`;
    if (S.query)
      return loadFeed(version, S.searchKind || "search", false, S.query);
    return;
  }
  if (S.page === "accounts") {
    view.innerHTML = accountsPage();
    return;
  }
  if (S.page === "jobs") {
    S.jobs = await api("/jobs");
    if (version !== S.version) return;
    view.innerHTML = jobsPage();
    return;
  }
  if (S.page === "sources") {
    [S.sources, S.entries] = await Promise.all([
      api("/sources"),
      api("/entries"),
    ]);
    if (version !== S.version) return;
    view.innerHTML = sourcesPage();
    return;
  }
  if (S.page === "rules") {
    [S.rules, S.sources] = await Promise.all([api("/rules"), api("/sources")]);
    if (version !== S.version) return;
    view.innerHTML = rulesPage();
    return;
  }
  if (S.page === "settings") {
    const [config, users] = await Promise.all([
      api("/ai"),
      S.user.role === "admin" ? api("/users") : Promise.resolve([]),
    ]);
    if (version !== S.version) return;
    S.ai = config;
    S.users = users;
    view.innerHTML = settingsPage();
    return;
  }
  if (S.page === "tools") {
    view.innerHTML = toolsPage();
    return;
  }
  if (S.page === "articles") {
    if (needAccount()) return;
    view.innerHTML = `<div class="page-pad"><div class="page-intro"><div><h2>长一点，也值得。</h2><p>Markdown 编辑，支持插图与嵌入贴文。需要 X Premium 权限。</p></div><button class="primary" data-action="compose-article">新建文章</button></div><div class="row"><button class="secondary" data-action="list-articles" data-type="Draft">X 文章草稿</button><button class="secondary" data-action="list-articles" data-type="Published">已发布文章</button></div><div id="article-results">${empty("你的长文空间", "创建文章后可先保存到 X 草稿，再选择发布。", "article")}</div></div>`;
    return;
  }
  if (S.page === "messages") {
    if (needAccount()) return;
    S.chat ||= {account: S.account, unlocked: false, has_saved_pin: false, ready: false, busy: false, inbox: null, inboxLoading: false, error: "", inboxError: ""};
    view.innerHTML = messagesPage();
    const status = await api(`/accounts/${S.account}/chat/status`);
    if (version !== S.version) return;
    Object.assign(S.chat, status, {ready: true});
    renderChatSecurity();
    return refreshChatInbox();
  }
}
function messagesPage() {
  return `<div class="page-pad chat-workspace"><div class="page-intro"><div><h2>你的私信会话</h2><p>会话读取与聊天密码，集中在这里管理。</p></div><a class="secondary" href="https://x.com/i/chat" target="_blank" rel="noopener noreferrer">在 X 打开 ↗</a></div><section class="panel" id="chat-security">${loading()}</section><section class="panel" id="chat-inbox">${loading()}</section><div class="footnote">${icon("shield")}<span>私信在浏览器中加密和解密，通过账号 Cookie 与绑定代理收发。页面打开并解锁时每 30 秒刷新；养护期只读。当前支持文字私信。</span></div></div>`;
}
function renderChatSecurity() {
  if (S.page !== "messages" || !S.chat || !$("#chat-security")) return;
  const c = S.chat;
  $("#chat-security").innerHTML = `<div class="row between"><div class="row">${icon("shield")}<h3>X Chat 聊天密码</h3></div>${badge(c.unlocked ? "本次会话已解锁" : "聊天已锁定", c.unlocked ? "" : "gray")}</div><p class="chat-help">填写已经在 X Chat 设置的密码，用于恢复聊天密钥。它与控制台登录密码不同。</p><form data-form="chat-password" class="chat-pin-form"><div class="field"><label for="chat-pin">聊天密码${c.has_saved_pin ? " · 已加密保存" : ""}</label><input id="chat-pin" name="pin" type="password" inputmode="numeric" autocomplete="off" minlength="4" maxlength="128" placeholder="${c.has_saved_pin ? "输入新值可替换已保存的密码" : "输入已在 X Chat 设置的密码"}" required ${c.busy ? "disabled" : ""}></div><button class="secondary" type="submit" ${c.busy ? "disabled" : ""}>保存密码</button></form><div class="chat-controls">${c.unlocked ? '<button class="secondary" data-action="chat-lock">锁定聊天</button>' : `<button class="primary" data-action="chat-unlock" ${!c.has_saved_pin || c.busy ? "disabled" : ""}>${icon("shield")}${c.busy ? "正在解锁…" : "使用已保存密码解锁"}</button>`}${c.has_saved_pin ? `<button class="text-btn muted" data-action="chat-password-clear" ${c.busy ? "disabled" : ""}>清除已保存的密码</button>` : ""}</div>${c.progress ? `<p class="chat-help" role="status" aria-live="polite">${esc(c.progress)}</p>` : ""}${c.error ? `<div class="form-error show" role="alert">${esc(c.error)}</div>` : ""}<p class="tiny muted chat-help">密码加密存储在 MySQL，不展示原值。恢复的密钥仅保留在当前浏览器页面；离开私信页后自动锁定。</p>`;
}
function renderChatInbox() {
  if (S.page !== "messages" || !S.chat || !$("#chat-inbox")) return;
  const c = S.chat, inbox = c.inbox;
  const draft = $("#chat-text");
  if (draft && draft.dataset.conversation === c.selected) c.draft = draft.value;
  let body = c.inboxLoading && !inbox ? loading() : "";
  if (c.inboxError) body += `<div class="form-error show">${esc(c.inboxError)}</div>`;
  if (inbox) {
    if (!inbox.item_count && !inbox.conversations.length) body += empty("暂无私信会话", "输入对方的 X 用户名可以打开会话。", "mail");
    else body += `<div class="chat-conversation-list">${inbox.conversations.map(t => `<button class="chat-conversation ${t.id === c.selected ? "selected" : ""}" data-action="chat-open" data-id="${esc(t.id)}" ${c.sending ? "disabled" : ""}>${avatar(t.title)}<span class="grow"><b>${esc(t.title)}</b><small>${esc(t.participants?.map(p => p.handle ? "@" + p.handle : p.name).join(" · ") || "加密会话")}</small></span>${icon("chevron")}</button>`).join("")}</div>`;
    if (inbox.unrecognized_items) body += `<div class="notice">${inbox.unrecognized_items} 条数据尚未识别，请在 X 核对。</div>`;
    if (inbox.message_requests) body += `<p class="chat-help">X 返回 ${inbox.message_requests} 条消息请求，请在 X 中处理。</p>`;
    if (inbox.cursor) body += `<button class="secondary chat-more" data-action="chat-inbox-more" ${c.inboxLoading ? "disabled" : ""}>加载更多会话</button>`;
  }
  $("#chat-inbox").innerHTML = `<div class="row between"><h3>收件箱${inbox ? ` · ${inbox.conversations.length} 个会话` : ""}</h3><button class="secondary" data-action="chat-refresh" ${c.inboxLoading || c.sending ? "disabled" : ""}>${icon("refresh")}刷新</button></div><form data-form="chat-recipient" class="chat-recipient"><input name="handle" aria-label="对方 X 用户名" placeholder="输入 @用户名" maxlength="16" required><button class="secondary" ${c.sending ? "disabled" : ""}>打开会话</button>${errorSlot()}</form>${inbox ? `<p class="tiny muted chat-help">最近同步 ${date(inbox.synced_at)}</p>` : ""}${body}<div id="chat-thread"></div>`;
  renderChatThread();
}
function renderChatThread() {
  const c = S.chat;
  if (!c || !$("#chat-thread") || !c.selected) return;
  const draft = $("#chat-text");
  if (draft && draft.dataset.conversation === c.selected) c.draft = draft.value;
  const thread = c.inbox?.conversations.find(t => t.id === c.selected);
  const own = S.accounts.find(a => a.id === S.account)?.x_id;
  const sender = id => thread?.participants?.find(p => p.x_id === id)?.name || (id === own ? "我" : "聊天成员");
  const canSend = c.unlocked && c.can_write && !c.sending && !c.threadLoading && !c.sendUncertain;
  $("#chat-thread").innerHTML = `<div class="chat-thread"><div class="row between"><h3>${esc(thread?.title || "会话内容")}</h3><button class="text-btn" data-action="chat-thread-refresh" ${c.threadLoading || c.sending ? "disabled" : ""}>刷新消息</button></div>${c.has_more && c.before ? `<button class="secondary chat-more" data-action="chat-history" ${c.threadLoading || c.sending ? "disabled" : ""}>加载更早消息</button>` : ""}${c.threadLoading && !c.messages?.length ? loading() : ""}${c.threadError ? `<div class="notice">${esc(c.threadError)}</div>` : ""}<div class="chat-messages">${(c.messages || []).map(m => `<article class="chat-bubble ${m.sender_id === own ? "own" : ""}"><div class="tiny muted">${esc(sender(m.sender_id))} · ${date(m.created)}</div><p>${esc(m.text)}</p></article>`).join("") || (!c.threadLoading ? `<p class="chat-help">${c.system_event_count ? '聊天密钥和设置已同步，暂时还没有聊天消息。' : '暂时还没有聊天消息。'}</p>` : "")}</div>${c.failed_count ? `<p class="chat-help">${c.failed_count} 条事件未通过解密或签名校验。</p>` : ""}${c.diagnostic ? `<details class="chat-help"><summary>解密诊断</summary>${esc(c.diagnostic)}</details>` : ""}<form data-form="chat-send" class="chat-compose"><textarea id="chat-text" name="text" data-conversation="${esc(c.selected)}" aria-label="私信内容" placeholder="${!c.can_write ? "养护期只读，结束后可发送私信" : !c.unlocked ? "请先解锁聊天" : "写一条私信…"}" maxlength="10000" required ${!canSend ? "disabled" : ""}>${esc(c.draft || "")}</textarea>${c.sendError ? `<div class="form-error show">${esc(c.sendError)}</div>` : ""}${errorSlot()}<div class="row between"><span class="tiny muted">${c.sendNote ? esc(c.sendNote) : "端到端加密 · 文字消息"}</span><button class="primary" ${!canSend ? "disabled" : ""}>${c.sending ? "正在发送…" : "发送私信"}</button></div></form></div>`;
}
async function refreshChatInbox(more = false) {
  const c = S.chat, account = S.account;
  if (!c || c.inboxLoading || c.sending) return;
  c.inboxLoading = true; c.inboxError = "";
  const cursor = more ? c.inbox?.cursor : null;
  try {
    const result = await api(`/accounts/${account}/chat/inbox${cursor ? "?cursor=" + encodeURIComponent(cursor) : ""}`);
    if (S.chat !== c) return;
    if (more) result.conversations = [...new Map([...c.inbox.conversations,...result.conversations].map(t => [t.id,t])).values()];
    else if (c.selected && !result.conversations.some(t => t.id === c.selected)) {
      const selected = c.inbox?.conversations.find(t => t.id === c.selected);
      if (selected) result.conversations.push(selected);
    }
    c.inbox = result;
  } catch (e) { if (S.chat === c) c.inboxError = e.message; }
  finally { if (S.chat === c) { c.inboxLoading = false; renderChatInbox(); } }
}
async function unlockChat() {
  const c = S.chat;
  if (!c || c.busy) return;
  c.busy = true; c.error = ""; c.progress = "正在准备解锁"; renderChatSecurity();
  S.chatVault?.dispose();
  const vault = new ChatVault(S.account, S.csrf, text => { if (S.chat === c) { c.progress = text; renderChatSecurity(); } });
  S.chatVault = vault;
  try {
    const result = await vault.unlock();
    if (S.chat !== c) { vault.dispose(); return; }
    c.unlocked = result.unlocked;
    c.progress = "聊天密钥已恢复，并确认属于当前 X 账号。";
  } catch (e) {
    vault.dispose();
    if (S.chat === c) { c.error = e.message + (e.diagnostic ? " 诊断：" + e.diagnostic : ""); c.unlocked = false; }
  } finally { if (S.chat === c) { c.busy = false; renderChatSecurity(); renderChatInbox(); } }
}
async function openChatConversation(id, more = false) {
  const c = S.chat, account = S.account, vault = S.chatVault;
  if (!c || c.sending || c.threadLoading) return;
  const changed = c.selected !== id;
  if (changed) Object.assign(c,{messages:[],draft:"",before:null,key_before:null,has_more:false,sendError:"",sendUncertain:false,sendNote:"",diagnostic:""});
  c.selected = id; c.threadError = "";
  if (!c.unlocked || !vault) { c.threadError = "请先使用聊天密码解锁，再读取加密消息。"; renderChatInbox(); return; }
  c.threadLoading = true;
  if (changed) renderChatInbox(); else renderChatThread();
  try {
    const params = new URLSearchParams();
    if (more && c.before) params.set("before", c.before);
    if (more && c.key_before) params.set("key_before", c.key_before);
    const result = await api(`/accounts/${account}/chat/conversations/${encodeURIComponent(id)}?${params}`);
    if (S.chat !== c) return;
    const conversation = c.inbox?.conversations.find(t => t.id === id);
    const decoded = await vault.decrypt(result.events, conversation?.participant_ids || [], result.page_events);
    if (S.chat !== c || c.selected !== id) return;
    const messages = [...new Map([...(c.messages || []),...decoded.messages].map(m => [m.id,m])).values()].sort((a,b) => (a.created || 0)-(b.created || 0));
    const prior = c.before;
    Object.assign(c,decoded,{messages,before:result.before || decoded.before,system_event_count:result.system_event_count || 0});
    c.has_more = result.has_more && !!c.before && (!more || c.before !== prior);
    if (result.has_more && !c.has_more) c.threadError = "历史消息游标未推进，已停止翻页；请在 X 核对。";
  } catch (e) { if (S.chat === c) c.threadError = e.message; }
  finally { if (S.chat === c) { c.threadLoading = false; renderChatThread(); } }
}
async function sendChatMessage(text) {
  const c = S.chat, vault = S.chatVault;
  if (!c?.unlocked || !vault) throw new Error("请先解锁聊天");
  if (!c.can_write || c.sending || c.threadLoading || c.sendUncertain) throw new Error("当前不能发送私信，请检查养护状态和上一条消息的结果");
  c.sending = true; c.sendError = ""; c.draft = text; c.sendNote = "";
  renderChatThread();
  try {
    const conversation = c.inbox?.conversations.find(t => t.id === c.selected);
    const result = await vault.send(c.selected,text,conversation?.participant_ids || []);
    if (S.chat !== c) return;
    c.messages = [...new Map([...(c.messages || []),...result.messages].map(m => [m.id,m])).values()];
    c.draft = ""; const field = $("#chat-text"); if (field) field.value = "";
    c.sendNote = "X 已确认消息";
  } catch(e) {
    if (S.chat === c) { c.sendError = e.message; c.sendUncertain = true; }
  } finally { if (S.chat === c) { c.sending = false; renderChatThread(); } }
}

function accountsPage() {
  return `<div class="page-pad"><div class="page-intro"><div><h2>你的账号，一目了然</h2><p>每个账号绑定独立代理，再登录 X。<br><button class="text-btn" data-page="maintenance">养护总览</button> · <button class="text-btn" data-page="keywords">关键词目录</button></p></div><button class="primary" data-action="add-account">${icon("plus")}添加账号</button></div>${S.accounts.map((a) => `<div class="card"><div class="row">${avatar(a.name, a.avatar, "large")}<div class="grow"><h3>${esc(a.name)}</h3><p>${a.handle ? "@" + esc(a.handle) : "等待登录验证"}</p></div>${badge(a.status === "connected" ? "已连接" : a.status === "logging_in" ? "登录中" : "待登录", a.status === "connected" ? "" : "orange")}</div><div class="proxy-path">${icon("shield")}<span>${esc(a.proxy)}</span></div>${policyCard(a)}<div class="job-meta">Cookie 同步：${date(a.cookie_updated)} · Go 网关 → 专属代理 → X</div><div class="actions"><button data-action="login-account" data-id="${a.id}">${a.status === "connected" ? "重新登录 / 更新会话" : "登录 X"}</button><button data-action="change-proxy" data-id="${a.id}">更换代理</button><button data-action="proxy-test" data-id="${a.id}">测试代理</button><button data-action="login-logs" data-id="${a.id}">登录日志</button><button data-action="configure-maintenance" data-id="${a.id}">养护配置</button>${a.status === "connected" ? `<button data-action="switch-mine" data-id="${a.id}">查看贴文</button>` : ""}<button class="danger" data-action="delete-account" data-id="${a.id}">移除账号</button></div></div>`).join("") || empty("连接你的第一个 X 账号", "先保存账号名称和代理，再使用账密登录或导入现有 Cookie。", "users")}<div class="notice">${icon("shield")}账号 Cookie 和代理密码加密存储。代理变更后需要重新登录，自动化会暂停，排期会转回草稿。</div></div>`;
}
const states = {
  draft: ["草稿", "gray"],
  queued: ["待发布", "blue"],
  sending: ["发布中", "blue"],
  sent: ["已完成", ""],
  failed: ["失败", "red"],
  uncertain: ["待核对", "orange"],
};
function jobsPage() {
  const list = S.jobs.filter(
    (j) =>
      S.jobFilter === "all" ||
      (S.jobFilter === "history"
        ? ["sent", "failed", "uncertain"].includes(j.state)
        : S.jobFilter === "queued"
          ? ["queued", "sending"].includes(j.state)
          : j.state === "draft"),
  );
  return `<div class="tabs">${[
    ["draft", "草稿箱"],
    ["queued", "发布计划"],
    ["history", "发布记录"],
  ]
    .map(
      ([k, v]) =>
        `<button class="${S.jobFilter === k ? "active" : ""}" data-action="jobs-filter" data-type="${k}">${v}</button>`,
    )
    .join(
      "",
    )}</div><div class="page-pad"><div class="row between"><span class="small muted">${list.length} 条内容</span><button class="secondary" data-action="compose">${icon("plus")}开始创作</button></div><div class="divider"></div>${list.map((j) => `<article class="card"><div class="row between"><div class="row"><span class="small">${esc(j.handle ? "@" + j.handle : j.account_name)}</span><span class="stat-chip">${{ post: "贴文", thread: "串文", article: "文章" }[j.payload.kind]}</span></div>${badge(...(states[j.state] || ["未知", "gray"]))}</div>${j.payload.title ? `<h3>${esc(j.payload.title)}</h3>` : ""}<div class="job-text">${esc(j.payload.kind === "thread" ? j.payload.texts.join("\n\n—\n\n") : j.payload.text)}</div><div class="job-meta"><span>${["queued", "sending"].includes(j.state) ? "计划发布" : "创建于"} ${date(["queued", "sending"].includes(j.state) ? j.scheduled : j.created)}</span>${j.rule_id ? "<span>自动化生成</span>" : ""}</div>${j.error ? `<div class="job-error">${esc(j.error)}</div>` : ""}<div class="job-result">${(j.result.tweet_ids || []).map((id, i) => `<a href="https://x.com/i/status/${esc(id)}" target="_blank" rel="noopener noreferrer">在 X 查看${i ? " " + (i + 1) : ""} ↗</a>`).join("")}${j.result.edit_url ? `<a href="${safeURL(j.result.edit_url)}" target="_blank" rel="noopener noreferrer">打开文章 ↗</a>` : ""}</div><div class="actions">${j.state === "draft" ? `<button data-action="edit-job" data-id="${j.id}">编辑 / 发布</button><button class="danger" data-action="delete-job" data-id="${j.id}">删除草稿</button>` : j.state === "queued" ? `<button data-action="cancel-job" data-id="${j.id}">取消排期，转回草稿</button>` : j.state !== "sending" ? `<button data-action="copy-job" data-id="${j.id}">复制到新草稿</button>` : '<span class="muted small">正在通过代理发送…</span>'}</div></article>`).join("") || empty(S.jobFilter === "draft" ? "你的灵感，值得留存" : S.jobFilter === "queued" ? "让内容准时遇见读者" : "每一次发布，都有迹可循", S.jobFilter === "draft" ? "写下第一个想法，或让 AI 帮你起草。" : "发布和自动化结果将在这里显示。", "post")}</div>`;
}
function sourcesPage() {
  return `<div class="page-pad"><div class="page-intro"><div><h2>保持好奇，保持更新</h2><p>订阅 RSS / Atom，或提取 AI 网站的最新内容。</p></div><button class="primary" data-action="add-source">${icon("plus")}添加来源</button></div>${S.sources.map((s) => `<div class="card"><div class="row"><div class="grow"><h3>${esc(s.name)}</h3><p>${esc(s.url)}</p></div>${badge(s.kind === "rss" ? "RSS / Atom" : "网页", "blue")}</div><div class="job-meta">上次采集：${date(s.last_fetch)}</div>${s.error ? `<div class="job-error">${esc(s.error)}</div>` : ""}<div class="actions"><button data-action="refresh-source" data-id="${s.id}">立即采集</button><button class="danger" data-action="delete-source" data-id="${s.id}">移除来源</button></div></div>`).join("") || empty("让信息主动找到你", "添加资讯源后，点击采集，即可将热点交给 AI 总结成贴文。", "globe")}<div class="section-label"><span>最新采集 · ${S.entries.length} 条</span><span>按来源发布时间排序</span></div>${S.entries.map((e) => `<article class="source-entry"><span class="small muted">${esc(e.source_name)} · ${date(e.published || e.fetched)}</span><h3>${esc(e.title)}</h3><p>${esc(e.summary)}</p><div class="row"><button class="secondary" data-action="entry-compose" data-id="${e.id}">${icon("spark")}总结并写成贴文</button><a class="small" href="${safeURL(e.url)}" target="_blank" rel="noopener noreferrer">阅读原文 ↗</a></div></article>`).join("")}</div>`;
}
function rulesPage() {
  return `<div class="page-pad"><div class="page-intro"><div><h2>把重复，交给自动化</h2><p>采集 → 总结 → 生成草稿，或按计划自动发布。</p></div><button class="primary" data-action="add-rule">${icon("plus")}新建任务</button></div>${S.rules.map((r) => `<div class="card"><div class="row between"><h3>${esc(r.name)}</h3>${badge(r.running ? "正在运行" : r.enabled ? "运行中" : "已暂停", r.enabled ? "" : "gray")}</div><p>${esc(r.prompt)}</p><div class="row wrap job-meta"><span>每 ${r.interval_minutes} 分钟</span><span>24 小时内最多 ${r.daily_limit} 条</span><span>${r.mode === "publish" ? "自动发布" : "生成草稿"}</span></div><div class="notice small">${esc(r.last_result || "任务就绪，等待首次运行")}<br><span class="tiny">${r.enabled ? "下次运行：" + date(r.next_run) : "启用后会按设定周期运行"}</span></div><div class="actions"><button data-action="edit-rule" data-id="${r.id}">编辑</button>${r.enabled ? `<button data-action="run-rule" data-id="${r.id}">立即运行</button><button data-action="pause-rule" data-id="${r.id}">暂停</button>` : `<button data-action="enable-rule" data-id="${r.id}">启用</button>`}<button class="danger" data-action="delete-rule" data-id="${r.id}">删除</button></div></div>`).join("") || empty("你的第一个内容工作流", "连接账号和 AI，添加热点来源，再创建自动化。默认生成草稿，由你决定何时发布。", "bolt")}<div class="notice">同一来源内容不会重复生成。发送结果不明确时会保留记录等待核对，不会自动重发。</div></div>`;
}
function settingsPage() {
  const c = S.ai;
  return `<div class="page-pad settings-layout"><section class="panel"><form data-form="ai"><div class="page-intro"><div><h2>你的 AI 创作伙伴</h2><p>支持 OpenAI 及兼容 Chat Completions 格式的服务。</p></div>${badge(c.configured ? "已配置" : "未连接", c.configured ? "" : "gray")}</div>${field("API 基础地址", "base_url", "https://api.openai.com/v1", "url", c.base_url, "required")}${field("API Key", "api_key", c.has_key ? "已保存，留空保留原密钥" : "填写服务商提供的密钥", "password", "", 'autocomplete="off"')}${field("模型名称", "model", "填写服务商支持的模型标识", "text", c.model, "required")}${textarea("写作偏好", "instruction", c.instruction, "例如：用中文，简洁真诚，有观点，避免夸张营销语气。")}<details><summary>服务兼容选项</summary><div class="field"><label for="token-parameter">输出预算参数</label><select id="token-parameter" name="token_parameter">${[
    ["auto", "自动选择（推荐）"],
    ["max_tokens", "传统兼容服务 · max_tokens"],
    ["max_completion_tokens", "新版 / 推理模型 · max_completion_tokens"],
  ]
    .map(
      ([v, l]) =>
        `<option value="${v}" ${(c.token_parameter || "auto") === v ? "selected" : ""}>${l}</option>`,
    )
    .join(
      "",
    )}</select><small>当服务报告参数不支持时，可根据服务商文档切换。</small></div></details>${errorSlot()}<div class="form-footer"><span class="tiny muted">API 密钥加密保存，不会返回浏览器。</span><button class="primary">保存 AI 配置</button></div></form></section><section class="panel"><div class="section-heading"><h3>工作台功能</h3></div><div class="shortcut-grid"><button class="secondary" data-page="maintenance">${icon("shield")}账号养护</button><button class="secondary" data-page="keywords">${icon("bookmark")}关键词目录</button><button class="secondary" data-page="sources">${icon("globe")}热点来源</button><button class="secondary" data-page="rules">${icon("bolt")}自动化任务</button><button class="secondary" data-page="articles">${icon("article")}文章管理</button><button class="secondary" data-page="tools">${icon("code")}API 工具箱</button><button class="secondary" data-page="messages">${icon("mail")}私信</button></div></section><section class="panel security-panel"><div class="section-heading"><h3>账户与安全</h3></div><div class="row wrap"><button class="text-btn" data-action="password">修改登录密码</button><button class="text-btn" data-action="audit">查看操作日志</button><button class="text-btn danger" data-action="logout">退出登录</button></div>${S.user.role === "admin" ? `<div class="divider"></div><div class="row between"><h3>工作台用户</h3><button class="secondary" data-action="add-user">添加用户</button></div><div class="scroll-table"><table><thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>${S.users.map((u) => `<tr><td>${esc(u.username)}</td><td>${u.role === "admin" ? "管理员" : "成员"}</td><td>${u.disabled ? "已停用" : "正常"}</td><td><button class="text-btn" data-action="edit-user" data-id="${u.id}">管理</button></td></tr>`).join("")}</tbody></table></div><p class="small muted">每位用户的 X 账号、AI 配置和内容独立隔离。</p>` : ""}</section></div>`;
}
function toolsPage() {
  return `<div class="page-pad"><div class="page-intro"><div><h2>能力探索器</h2><p>详情、评论、文章及 X Chat 的结构化读取。发布与互动请使用对应页面。</p></div></div><form class="panel" data-form="explorer"><div class="field"><label for="operation">接口能力</label><select name="operation" id="operation">${S.capabilities.reads.map((r) => `<option value="${r.id}">${esc(r.label)}</option>`).join("")}</select></div><div id="explorer-fields"></div>${errorSlot()}<button class="primary">执行读取</button></form><div id="explorer-result"></div><div class="notice">已接入：时间线、搜索、自己的贴文、详情与评论、用户资料、发帖/回复/引用、长帖、串文、点赞/转帖/书签、关注、媒体上传、文章草稿与发布、X Chat 读取。<br>文字私信可在私信页解锁后收发，养护期仅可读取。</div></div>`;
}
async function boot() {
  try {
    const status = await api("/auth/status");
    if (!status.initialized) {
      renderLogin(true);
      return;
    }
    try {
      const auth = await api("/auth/me");
      S.user = auth.user;
      S.csrf = auth.csrf;
    } catch {
      renderLogin(false);
      return;
    }
    await refreshBase();
    await navigateRoute(location.hash || "#home");
  } catch (e) {
    $("#app").innerHTML =
      `<div class="boot"><p>${esc(e.message)}</p><button class="secondary" data-action="reload">重试</button></div>`;
  }
}
document.addEventListener("click", async (event) => {
  const el = event.target.closest("[data-action],[data-page]");
  if (!el || el.disabled) return;
  if (el.tagName === "A" && (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
  event.preventDefault();
  if (el.dataset.page) {
    if ($("#modal").open && !S.modal?.busy) closeModal();
    await navigate(el.dataset.page);
    return;
  }
  if (el.dataset.action === "reload") {
    location.reload();
    return;
  }
  if (el.dataset.action === "close") {
    closeModal();
    return;
  }
  el.disabled = true;
  try {
    await handleAction(el.dataset.action, el);
  } catch (e) {
    toast(e.message);
  } finally {
    el.disabled = false;
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  const btn =
    event.submitter || $('button[type="submit"],button.primary', form);
  if (btn) btn.disabled = true;
  const error = $(".form-error", form);
  if (error) error.classList.remove("show");
  try {
    const f = new FormData(form),
      data = Object.fromEntries(f);
    if (["login", "setup"].includes(form.dataset.form)) {
      const auth = await api("/auth/" + form.dataset.form, {
        method: "POST",
        body: data,
      });
      form.reset();
      S.user = auth.user;
      S.csrf = auth.csrf;
      await refreshBase();
      await navigate("home");
    } else await handleForm(form, f, data, event.submitter);
  } catch (e) {
    showError(form, e);
  } finally {
    if (btn) btn.disabled = false;
  }
});
document.addEventListener("change", async (event) => {
  if (event.target.id === "search-kind") {
    $("#search-product").disabled = event.target.value !== "search";
  }
  if (event.target.id === "account-switch") {
    S.account = event.target.value;
    localStorage.setItem("xapis-account", S.account);
    await navigate(S.page);
  }
  if (event.target.id === "operation") renderExplorerFields();
  if (event.target.id === "schedule") updateComposePermissions();
  if (event.target.id === "compose-account") {
    S.modal.media = [];
    renderUploads();
    $("#compose-policy").innerHTML = policyCard(
      S.accounts.find((a) => a.id === event.target.value),
    );
    updateComposePermissions();
  }
  if (event.target.name === "kind" && $("#compose-form")) updateComposeKind();
  if (event.target.id === "media-files") await uploadFiles(event.target.files);
});
document.addEventListener("input", (event) => {
  if (event.target.name === "text" || event.target.name === "long")
    updateWeight();
});
$("#modal").addEventListener("cancel", (event) => {
  if (S.modal?.busy) event.preventDefault();
});
function onRouteChange() {
  if (S.user && location.hash.slice(1) !== S.route) navigateRoute(location.hash);
}
window.addEventListener("hashchange", onRouteChange);
window.addEventListener("popstate", onRouteChange);
boot();
function accountForm() {
  modal(
    "连接 X 账号",
    `<form data-form="account"><div class="steps"><span class="step"><i>1</i>账号名称</span>${icon("chevron")}<span class="step"><i>2</i>绑定代理</span>${icon("chevron")}<span class="step"><i>3</i>登录验证</span></div>${field("账号名称", "name", "例如：我的 AI 观察号", "text", "", 'required maxlength="80"')}${field("账号专属代理", "proxy", "http://用户名:密码@代理主机:端口", "password", "", 'required autocomplete="off"')}${field("只读养护天数", "warmup_days", "", "number", 4, 'required min="1" max="90"')}<div class="notice">默认首次成功登录后的前 4 天只读；第 5～7 天每日最多 2 篇，满 7 天后解除两篇限制。<br>支持 HTTP、HTTPS、SOCKS5 代理。先绑定代理，再登录 X；登录和后续请求均使用该代理。代理密码将加密保存。</div>${errorSlot()}<div class="form-footer"><span class="small muted">下一步：登录或导入 Cookie</span><button class="primary">保存并继续 ${icon("arrow")}</button></div></form>`,
  );
}
function loginAccount(id) {
  const a = S.accounts.find((x) => x.id === id);
  if (!a) return;
  modal(
    "登录 " + a.name,
    `<form data-form="account-login"><div class="login-progress" role="status" aria-live="polite" hidden></div><div class="proxy-path">${icon("shield")}${esc(a.proxy)}</div><div class="notice">连接会通过此账号已绑定的代理。已有会话可粘贴 Cookie；否则填写 X 用户名和密码。Cookie 非空时优先验证 Cookie；使用账密登录时请清空 Cookie。</div>${field("X 用户名", "username", "@用户名 / 邮箱", "text", "", 'autocomplete="off"')}${field("X 密码", "password", "仅用于本次登录，不会保存", "password", "", 'autocomplete="off"')}${textarea("或导入浏览器 Cookie", "cookies", "", "auth_token=…; ct0=…; twid=…", 'autocomplete="off"')}<details><summary>高级：Castle 浏览器 profile（可选）</summary>${textarea("Profile JSON", "profile", "", "粘贴现有 SDK 所需的 Rl/raw profile JSON")}</details>${errorSlot()}<div class="form-footer"><span class="tiny muted">遇到验证码或设备验证时，先在 X 完成验证再导入 Cookie。</span><button class="primary">登录并验证</button></div></form>`,
    { account: id },
  );
}
function sourceForm() {
  modal(
    "添加热点来源",
    `<form data-form="source">${field("来源名称", "name", "例如：AI 产品动态", "text", "", 'required maxlength="80"')}${field("来源地址", "url", "https://example.com/feed.xml", "url", "", "required")}<div class="field"><label for="source-kind">内容格式</label><select name="kind" id="source-kind"><option value="rss">RSS / Atom 订阅</option><option value="web">网页正文快照</option></select><small>网页仅提取静态 HTML 正文；推荐优先使用 RSS。请填写最终地址，不跟随重定向。</small></div>${errorSlot()}<div class="form-footer"><span></span><button class="primary">添加来源</button></div></form>`,
  );
}
function ruleForm(rule = null) {
  if (!S.accounts.length) {
    toast("请先添加账号");
    navigate("accounts");
    return;
  }
  if (!S.sources.length) {
    toast("请先添加热点来源");
    navigate("sources");
    return;
  }
  const r = rule || {
    name: "",
    account_id: S.account,
    source_ids: [],
    prompt:
      "总结最新 AI 动态，提炼一个值得关注的观点，附原始来源链接，用中文写成简洁贴文。",
    mode: "draft",
    interval_minutes: 180,
    daily_limit: 3,
    enabled: false,
  };
  modal(
    rule ? "编辑自动化" : "创建内容工作流",
    `<form data-form="rule">${field("任务名称", "name", "例如：每日 AI 新鲜事", "text", r.name, 'required maxlength="100"')}<div class="field"><label for="rule-account">发布账号</label><select name="account_id" id="rule-account">${S.accounts.map((a) => `<option value="${a.id}" ${a.id === r.account_id ? "selected" : ""}>${esc(a.name)} ${a.status === "connected" ? "" : "（待登录）"}</option>`).join("")}</select></div><div class="field"><label>热点来源</label><div class="source-picks">${S.sources.map((s) => `<label class="check"><input name="source_ids" type="checkbox" value="${s.id}" ${r.source_ids.includes(s.id) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}</div></div>${textarea("AI 写作要求", "prompt", r.prompt, "", 'required maxlength="4000"')}<div class="fields">${field("执行间隔（分钟）", "interval_minutes", "", "number", r.interval_minutes, 'min="15" max="43200" required')}${field("最近 24 小时最多生成", "daily_limit", "", "number", r.daily_limit, 'min="1" max="24" required')}</div><div class="field"><label for="rule-mode">生成后如何处理</label><select id="rule-mode" name="mode"><option value="draft" ${r.mode === "draft" ? "selected" : ""}>保存到草稿箱，人工审核</option><option value="publish" ${r.mode === "publish" ? "selected" : ""}>直接自动发布到 X</option></select></div><label class="check"><input name="enabled" type="checkbox" ${r.enabled ? "checked" : ""}>保存后启用此任务</label><div class="notice">选择自动发布后，启用的任务会无人值守地发布到指定 X 账号。每次使用最多 3 条新来源，自动保留出处并去重。</div>${errorSlot()}<div class="form-footer"><span class="tiny muted">最短间隔 15 分钟</span><button class="primary">保存任务</button></div></form>`,
    { rule: rule?.id },
  );
}
function compose(options = {}) {
  if (!S.accounts.length) {
    toast("先添加一个账号即可保存草稿");
    accountForm();
    return;
  }
  const p = options.payload || {},
    account = options.account_id || S.account;
  const quick = $("#quick-text")?.value || "";
  const context = {
    editor: true,
    job: options.job,
    request: newRequestId(),
    account,
    media: (p.media || []).map((id) => ({ id, name: "已上传媒体" })),
    entries: options.entry_ids || [],
    sources: p.sources || [],
    busy: false,
  };
  modal(
    options.job ? "编辑草稿" : "写下你的下一条贴文",
    `<form data-form="compose" id="compose-form"><div id="compose-policy">${policyCard(S.accounts.find((a) => a.id === account))}</div><div class="fields"><div class="field"><label for="compose-account">发布到</label><select id="compose-account" name="account_id">${S.accounts.map((a) => `<option value="${a.id}" ${a.id === account ? "selected" : ""}>${esc(a.handle ? "@" + a.handle : a.name)}${a.status === "connected" ? "" : " · 待登录"}</option>`).join("")}</select></div><div class="field"><label for="compose-kind">内容类型</label><select id="compose-kind" name="kind"><option value="post" ${p.kind === "post" ? "selected" : ""}>贴文</option><option value="thread" ${p.kind === "thread" ? "selected" : ""}>串文 / Thread</option><option value="article" ${p.kind === "article" || options.article ? "selected" : ""}>文章 / Article</option></select></div></div><div class="ai-box"><h3>${icon("spark")}给 AI 一个方向，保留你的声音</h3><div class="field"><textarea name="ai_prompt" aria-label="AI 写作方向" placeholder="例如：用通俗的语言解读这次 AI 更新，表达一个自己的观点。">${options.entry_ids?.length ? "根据所选热点总结事实与意义，写一条中文贴文并保留来源链接。" : ""}</textarea></div><div class="row between"><span class="tiny muted">${options.entry_ids?.length ? "已关联 " + options.entry_ids.length + " 条热点资料" : "使用设置中的 AI 服务"}</span><button type="button" class="secondary" data-action="generate">${icon("spark")}一键编写</button></div></div><div id="article-fields" hidden>${field("文章标题", "title", "一个值得阅读的标题", "text", p.title || "", 'maxlength="250"')}${field("更新现有草稿 ID（可选）", "article_id", "留空将创建新文章", "text", p.article_id || "")}</div>${textarea("正文", "text", p.kind === "thread" ? (p.texts || []).join("\n\n---\n\n") : p.text || quick, "有什么值得分享？", 'class="compose-text" maxlength="25000" required')}<div class="row between"><span id="compose-help" class="tiny muted">贴文支持回复、引用、图片和视频。</span><span id="weight" class="weight"></span></div><div class="upload-list" id="upload-list"></div><div class="row wrap"><label class="secondary" for="media-files">${icon("image")}添加媒体<input type="file" id="media-files" accept="image/jpeg,image/png,image/gif,image/webp,video/mp4,video/quicktime" multiple hidden></label><span class="tiny muted">单文件 ≤ 50 MB · 媒体有效期约 24 小时</span></div><label class="check"><input name="allow_download" type="checkbox" checked>上传时允许媒体下载</label><label class="check" id="long-check"><input name="long" type="checkbox" ${p.long ? "checked" : ""}>Premium 长贴文 <small>需要 X Premium 权限</small></label><details><summary>回复、引用与文章发布选项</summary>${field("回复贴文 ID / 链接", "reply_to", "选填", "text", p.reply_to || "")}${field("引用贴文链接", "quote_url", "https://x.com/…/status/…", "url", p.quote_url || "")}<div id="article-options" hidden>${field("发布文章时附带的贴文", "caption", "选填", "text", p.caption || "")}<div class="field"><label for="reply-mode">文章回复权限</label><select id="reply-mode" name="reply_mode">${[
      ["", "默认"],
      ["All", "所有人"],
      ["Community", "你关注的人"],
      ["Verified", "已认证用户"],
      ["ByInvitation", "提及的用户"],
    ]
      .map(
        ([v, l]) =>
          `<option value="${v}" ${v === p.reply_mode ? "selected" : ""}>${l}</option>`,
      )
      .join(
        "",
      )}</select></div><label class="check"><input type="checkbox" name="publish_article" ${p.publish_article ? "checked" : ""}>直接发布文章 <small>未勾选时仅保存到 X 文章草稿</small></label></div></details><div class="field"><label for="schedule">计划时间（本地时区）</label><input type="datetime-local" name="scheduled" id="schedule"><small>留空表示立即执行。保存草稿时不会发布。</small></div>${context.sources.length ? `<div class="notice tiny">引用来源：${context.sources.map((s) => esc(s.title)).join(" · ")}</div>` : ""}${errorSlot()}<div class="form-footer"><button class="secondary" type="submit" name="intent" value="draft">保存草稿</button><button class="primary" type="submit" name="intent" value="queued">${icon("post")}确认并提交发布</button></div></form>`,
    context,
  );
  updateComposeKind();
  renderUploads();
  updateWeight();
  updateComposePermissions();
  if (options.schedule) $("#schedule").focus();
}
function updateComposeKind() {
  const form = $("#compose-form");
  if (!form) return;
  const article = form.elements.kind.value === "article",
    thread = form.elements.kind.value === "thread";
  $("#article-fields").hidden = !article;
  $("#article-options").hidden = !article;
  $("#long-check").hidden = article;
  form.elements.title.required = article;
  $("#compose-help").textContent = article
    ? "支持 Markdown；插图使用 ![](media:上传ID)，第一张媒体作为封面。"
    : thread
      ? "用独占一行的 --- 分隔串文，每条会回复上一条。"
      : "贴文支持回复、引用、图片和视频。";
  updateWeight();
}
function weight(text) {
  let count = 0,
    joined = false;
  for (const ch of text.replace(
    /https?:\/\/[^\s\u3000-\u303f\uff00-\uffef]+/gi,
    "x".repeat(23),
  )) {
    const cp = ch.codePointAt(0);
    if (
      [0x200d, 0xfe0e, 0xfe0f, 0x20e3].includes(cp) ||
      (cp >= 0x1f3fb && cp <= 0x1f3ff)
    ) {
      joined = cp === 0x200d;
      continue;
    }
    if (joined) {
      joined = false;
      continue;
    }
    count +=
      cp <= 4351 ||
      (cp >= 8192 && cp <= 8205) ||
      (cp >= 8208 && cp <= 8223) ||
      (cp >= 8242 && cp <= 8247)
        ? 1
        : 2;
  }
  return count;
}
function updateWeight() {
  const form = $("#compose-form");
  if (!form) return;
  const t = form.elements.text.value;
  const list =
    form.elements.kind.value === "thread" ? t.split(/\n\s*---\s*\n/) : [t];
  const w = Math.max(...list.map(weight));
  const el = $("#weight");
  el.textContent =
    form.elements.kind.value === "article"
      ? `${t.length} 字符`
      : `${list.length > 1 ? list.length + " 条 · 最大 " : ""}${w} / 280 权重`;
  el.classList.toggle("over", w > 280);
}
function renderUploads() {
  const el = $("#upload-list");
  if (!el || !S.modal) return;
  el.innerHTML = S.modal.media
    .map(
      (m) =>
        `<span class="upload-item"><span>${esc(m.name)}<br><code>media:${esc(m.id)}</code></span><button type="button" data-action="remove-media" data-id="${esc(m.id)}" aria-label="移除 ${esc(m.name)}">×</button></span>`,
    )
    .join("");
}
async function uploadFiles(files) {
  const form = $("#compose-form");
  if (!form || !S.modal) return;
  const owner = S.modal;
  try {
    if (owner.media.length + files.length > 4)
      throw new Error("最多添加 4 个媒体");
    owner.busy = true;
    for (const file of files) {
      if (file.size > 50 * 1024 * 1024) throw new Error("单文件不能超过 50 MB");
      const fd = new FormData();
      fd.append("file", file);
      fd.append(
        "purpose",
        form.elements.kind.value === "article" ? "article" : "post",
      );
      fd.append("allow_download", String(form.elements.allow_download.checked));
      const m = await api(
        "/accounts/" + form.elements.account_id.value + "/media",
        { method: "POST", body: fd },
      );
      owner.media.push(m);
      renderUploads();
    }
    toast("媒体已上传");
  } catch (e) {
    showError(form, e);
  } finally {
    owner.busy = false;
    $("#media-files").value = "";
  }
}
function renderExplorerFields() {
  const op = $("#operation");
  if (!op) return;
  const def = S.capabilities.reads.find((r) => r.id === op.value);
  $("#explorer-fields").innerHTML = Object.entries(def?.params || {})
    .map(([k, v]) =>
      field(
        esc(v),
        k,
        k === "user_ids" ? '["123456"]' : k === "lifecycle" ? "Draft" : "",
        "text",
        k === "lifecycle" ? "Draft" : "",
        v.includes("选填") ? "" : "required",
      ),
    )
    .join("");
}
async function confirmAction(title, text, action, context = {}) {
  context.request = newRequestId();
  modal(
    title,
    `<p class="muted small">${esc(text)}</p>${errorSlot()}<div class="form-footer"><button class="secondary" data-action="close">取消</button><button class="primary" data-action="confirm-${action}">确认</button></div>`,
    context,
  );
}
async function handleAction(action, el) {
  const id = el.dataset.id,
    type = el.dataset.type;
  if (
    [
      "add-keywords",
      "edit-keywords",
      "delete-keywords",
      "confirm-delete-keywords",
      "configure-maintenance",
      "maintenance-run",
      "maintenance-pause",
      "maintenance-logs",
    ].includes(action)
  )
    return maintenanceAction(action, id);
  if (action === "mobile-menu") {
    modal("工作台导航", `<div class="navigation-menu">${navs.map(([page, glyph, label]) => `<button data-page="${page}">${icon(glyph)}<span>${label}</span>${icon("chevron")}</button>`).join("")}</div>`);
    return;
  }
  if (action === "proxy-test") {
    toast("正在通过该账号代理检查 X 连接…");
    const r = await api("/accounts/" + id + "/proxy-test", { method: "POST" });
    toast(r.message + " · " + r.seconds + " 秒");
    return;
  }
  if (action === "login-logs") {
    const logs = await api("/accounts/" + id + "/request-logs");
    modal(
      "登录流程日志",
      `<div class="notice">显示真实 HTTP 状态、请求字段与脱敏响应；不记录密码、Cookie 和代理认证。</div>${logs.map((l) => `<div class="request-log"><div class="row between"><b>${esc(l.method)} ${l.status ?? esc(l.error_type || "本地处理")}</b><span class="tiny muted">${l.duration_ms} ms</span></div><p class="log-path">${esc(l.path)}</p><span class="tiny muted">${date(l.created)} · ${esc(l.attempt_id.slice(0, 8))}</span><details ${l.error_type || l.status >= 400 ? "open" : ""}><summary>查看请求字段和真实响应</summary><div class="tiny muted">字段：${esc(l.request_fields.join(", ") || "无请求字段")}</div><pre class="mono">${esc(l.response_excerpt)}</pre><pre class="mono">${esc(JSON.stringify(l.response_headers, null, 2))}</pre></details></div>`).join("") || '<p class="muted">暂时没有日志。新的登录尝试会在这里记录流程。</p>'}`,
    );
    return;
  }
  if (action === "refresh") {
    await refreshBase();
    await navigate(S.page);
    return;
  }
  if (action === "add-account") {
    accountForm();
    return;
  }
  if (action === "login-account") {
    loginAccount(id);
    return;
  }
  if (action === "change-proxy") {
    const a = S.accounts.find((a) => a.id === id);
    modal(
      "更换账号代理",
      `<form data-form="proxy"><p class="small muted">当前代理：${esc(a.proxy)}</p>${field("新代理地址", "proxy", "http://用户名:密码@主机:端口", "password", "", 'required autocomplete="off"')}<div class="notice warning">更换后会清除该账号登录会话、暂停自动化，并把待发布内容转回草稿。请重新登录后再启用任务。</div>${errorSlot()}<button class="primary">保存新代理</button></form>`,
      { account: id },
    );
    return;
  }
  if (action === "delete-account") {
    return confirmAction(
      "移除账号",
      "此操作会移除此账号及关联草稿、发布记录、媒体和自动化。X 上已发布的内容不会删除。",
      "delete-account",
      { account: id },
    );
  }
  if (action === "confirm-delete-account") {
    await api("/accounts/" + S.modal.account, { method: "DELETE" });
    closeModal();
    await refreshBase();
    return navigate("accounts");
  }
  if (action === "switch-mine") {
    S.account = id;
    localStorage.setItem("xapis-account", id);
    return navigate("mine");
  }
  if (action.startsWith("compose")) {
    compose({
      article: action === "compose-article",
      schedule: action === "compose-schedule",
    });
    return;
  }
  if (action === "entry-compose") {
    compose({ entry_ids: [id] });
    return;
  }
  if (action === "reply") {
    compose({ payload: { kind: "post", reply_to: id } });
    return;
  }
  if (action === "post-more") {
    const p = S.posts.find((p) => p.work_id === id);
    modal(
      "贴文操作",
      `<div class="column"><button class="secondary" data-action="detail" data-id="${esc(id)}">${icon("reply")}查看详情与评论</button><button class="secondary" data-action="quote" data-id="${esc(id)}">${icon("post")}引用这条贴文</button><a class="secondary" href="https://x.com/i/status/${esc(id)}" target="_blank" rel="noopener noreferrer">在 X 打开 ↗</a>${p?.user_id === current()?.x_id ? `<button class="secondary danger" data-action="delete-post" data-id="${esc(id)}">删除贴文</button>` : ""}</div>`,
    );
    return;
  }
  if (action === "detail") {
    closeModal();
    return openPost(id);
  }
  if (action === "back-from-post") {
    if (history.state?.xapisBack) history.back();
    else return navigate("home");
    return;
  }
  if (action === "load-comments") {
    return loadPost(S.version, true);
  }
  if (action === "quote") {
    closeModal();
    compose({
      payload: { kind: "post", quote_url: "https://x.com/i/status/" + id },
    });
    return;
  }
  if (action === "delete-post") {
    return confirmAction(
      "删除 X 贴文",
      "将从 X 删除这条贴文，此操作不可撤销。",
      "delete-post",
      { post: id },
    );
  }
  if (action === "confirm-delete-post") {
    await api(`/accounts/${S.account}/action`, {
      method: "POST",
      body: { action: "delete", target: S.modal.post },
    });
    closeModal();
    toast("贴文已删除");
    return navigate(S.page);
  }
  if (action === "interact") {
    await api(`/accounts/${S.account}/action`, {
      method: "POST",
      body: { action: type, target: id },
    });
    const p = S.posts.find((p) => p.work_id === id);
    if (p) {
      const pairs = {
          like: ["liked", "like_count", true],
          unlike: ["liked", "like_count", false],
          repost: ["retweeted", "retweet_count", true],
          unrepost: ["retweeted", "retweet_count", false],
          bookmark: ["bookmarked", "bookmark_count", true],
          unbookmark: ["bookmarked", "bookmark_count", false],
        },
        v = pairs[type];
      if (v) {
        p[v[0]] = v[2];
        p[v[1]] = Math.max(0, (Number(p[v[1]]) || 0) + (v[2] ? 1 : -1));
        el.closest(".feed-card").outerHTML = postCard(p, {focal: S.page === "post" && p.work_id === S.detailId});
      }
    }
    toast("操作成功");
    return;
  }
  if (action === "load-more") {
    return loadFeed(
      S.version,
      S.page === "mine"
        ? "mine"
        : S.page === "explore"
          ? S.searchKind || "search"
          : "home",
      true,
      S.query,
    );
  }
  if (action === "jobs-filter") {
    S.jobFilter = type;
    return navigate("jobs");
  }
  if (action === "edit-job" || action === "copy-job") {
    const j = S.jobs.find((j) => j.id === id);
    if (
      action === "copy-job" &&
      j.state === "uncertain" &&
      !confirm(
        "原任务发布结果不明，请先到 X 核对是否已发布。确定复制为新草稿？",
      )
    )
      return;
    compose({
      payload: j.payload,
      account_id: j.account_id,
      job: action === "edit-job" ? j.id : null,
    });
    return;
  }
  if (action === "delete-job") {
    await api("/jobs/" + id, { method: "DELETE" });
    await refreshBase();
    return navigate("jobs");
  }
  if (action === "cancel-job") {
    await api("/jobs/" + id + "/cancel", { method: "POST" });
    toast("已取消排期，转回草稿");
    await refreshBase();
    return navigate("jobs");
  }
  if (action === "remove-media") {
    S.modal.media = S.modal.media.filter((m) => m.id !== id);
    renderUploads();
    return;
  }
  if (action === "generate") {
    const form = $("#compose-form");
    if (S.modal.busy) throw new Error("正在处理，请稍候");
    const context = S.modal;
    context.busy = true;
    try {
      const topic = form.elements.ai_prompt.value.trim();
      const text = form.elements.text.value.trim();
      if (!topic && !text && !context.entries.length)
        throw new Error("先给 AI 一个主题，或输入需要润色的正文");
      const result = await api("/ai/generate", {
        method: "POST",
        body: {
          prompt: topic || "润色下列贴文，保留原意：\n" + text,
          entry_ids: context.entries,
          long:
            form.elements.long.checked ||
            form.elements.kind.value === "article",
        },
      });
      form.elements.text.value = result.text;
      context.sources = result.sources;
      updateWeight();
      toast("AI 草稿已生成，请审阅后发布");
    } finally {
      context.busy = false;
    }
    return;
  }
  if (action === "add-source") {
    sourceForm();
    return;
  }
  if (action === "refresh-source") {
    const r = await api("/sources/" + id + "/refresh", { method: "POST" });
    toast("已采集 " + r.count + " 条来源内容");
    return navigate("sources");
  }
  if (action === "delete-source") {
    return confirmAction(
      "移除热点来源",
      "将删除此来源和已采集的内容。被自动化引用的来源需要先调整任务。",
      "delete-source",
      { source: id },
    );
  }
  if (action === "confirm-delete-source") {
    await api("/sources/" + S.modal.source, { method: "DELETE" });
    closeModal();
    return navigate("sources");
  }
  if (action === "add-rule" || action === "edit-rule") {
    [S.sources, S.rules] = await Promise.all([api("/sources"), api("/rules")]);
    ruleForm(action === "edit-rule" ? S.rules.find((r) => r.id === id) : null);
    return;
  }
  if (action === "run-rule" || action === "pause-rule") {
    await api(
      "/rules/" + id + "/" + (action === "run-rule" ? "run" : "pause"),
      { method: "POST" },
    );
    toast(
      action === "run-rule"
        ? "任务已加入执行队列"
        : "任务已暂停，未发送内容已转回草稿",
    );
    return navigate("rules");
  }
  if (action === "enable-rule") {
    const r = S.rules.find((r) => r.id === id);
    ruleForm({ ...r, enabled: true });
    return;
  }
  if (action === "delete-rule") {
    return confirmAction(
      "删除自动化",
      "会停止此任务，尚未发送的内容会转回草稿。已生成的内容保留。",
      "delete-rule",
      { rule: id },
    );
  }
  if (action === "confirm-delete-rule") {
    await api("/rules/" + S.modal.rule, { method: "DELETE" });
    closeModal();
    return navigate("rules");
  }
  if (action === "list-articles") {
    const data = await api(`/accounts/${S.account}/explore`, {
      method: "POST",
      body: { operation: "articles", params: { lifecycle: type } },
    });
    const articles = findArticles(data);
    $("#article-results").innerHTML = articles.length
      ? articles
          .map(
            (a) =>
              `<div class="card"><h3>${esc(a.title || "无标题文章")}</h3><p>ID：${esc(a.id)}</p><div class="actions"><button data-action="edit-article" data-id="${esc(a.id)}">编辑内容</button><button data-action="publish-article" data-id="${esc(a.id)}">发布文章</button><button class="danger" data-action="delete-article" data-id="${esc(a.id)}">删除文章</button></div></div>`,
          )
          .join("")
      : `<div class="notice">未提取到文章列表，可查看 X 的完整响应。</div>`;
    $("#article-results").innerHTML +=
      `<details><summary>查看结构化响应</summary><pre class="mono">${esc(JSON.stringify(data, null, 2))}</pre></details>`;
    return;
  }
  if (action === "edit-article") {
    compose({ payload: { kind: "article", article_id: id } });
    return;
  }
  if (action === "publish-article" || action === "delete-article") {
    return confirmAction(
      action === "publish-article" ? "发布文章" : "删除文章",
      action === "publish-article"
        ? "将把这篇 X 草稿文章公开发布。"
        : "将从 X 删除这篇文章，此操作不可撤销。",
      "article",
      {
        article: id,
        type: action === "publish-article" ? "publish" : "delete",
      },
    );
  }
  if (action === "confirm-article") {
    await api(`/accounts/${S.account}/article-action`, {
      method: "POST",
      body: {
        action: S.modal.type,
        article_id: S.modal.article,
        caption: "",
        request_id: S.modal.request,
      },
    });
    closeModal();
    toast("文章操作完成");
    return;
  }
  if (action === "chat-refresh") { await refreshChatInbox(); if (S.chat?.selected) await openChatConversation(S.chat.selected); return; }
  if (action === "chat-inbox-more") return refreshChatInbox(true);
  if (action === "chat-history") return openChatConversation(S.chat.selected,true);
  if (action === "chat-thread-refresh") return openChatConversation(S.chat.selected);
  if (action === "chat-unlock") return unlockChat();
  if (action === "chat-lock") {
    S.chatVault?.dispose(); S.chatVault = null;
    Object.assign(S.chat,{unlocked:false,messages:null,draft:"",progress:"聊天已锁定",diagnostic:""});
    renderChatSecurity(); renderChatInbox();
    return;
  }
  if (action === "chat-password-clear") {
    await api(`/accounts/${S.account}/chat/password`, {method: "DELETE"});
    S.chatVault?.dispose(); S.chatVault = null;
    Object.assign(S.chat, {has_saved_pin: false, unlocked: false, messages: null});
    renderChatSecurity(); renderChatInbox();
    toast("已清除控制台保存的聊天密码；X 的聊天密码未改变");
    return;
  }
  if (action === "chat-open") return openChatConversation(id);
  if (action === "logout") {
    await api("/auth/logout", { method: "POST" });
    S.chatVault?.dispose(); S.chatVault = null; S.chat = null;
    S.user = null;
    S.csrf = "";
    renderLogin(false);
    return;
  }
  if (action === "password") {
    modal(
      "修改登录密码",
      `<form data-form="password">${field("当前密码", "current", "", "password", "", 'required autocomplete="current-password"')}${field("新密码", "new", "至少 12 位", "password", "", 'required minlength="12" autocomplete="new-password"')}${errorSlot()}<div class="form-footer"><span class="small muted">修改后所有会话将退出。</span><button class="primary">修改密码</button></div></form>`,
    );
    return;
  }
  if (action === "add-user") {
    modal(
      "添加工作台用户",
      `<form data-form="user">${field("用户名", "username", "", "text", "", 'required minlength="3" maxlength="40"')}${field("初始密码", "password", "至少 12 位", "password", "", 'required minlength="12"')}<div class="field"><label for="user-role">角色</label><select id="user-role" name="role"><option value="member">成员</option><option value="admin">管理员</option></select></div>${errorSlot()}<button class="primary">创建用户</button></form>`,
    );
    return;
  }
  if (action === "edit-user") {
    const u = S.users.find((u) => u.id === id);
    modal(
      "管理 " + u.username,
      `<form data-form="edit-user"><div class="field"><label for="user-role">角色</label><select id="user-role" name="role"><option value="member" ${u.role === "member" ? "selected" : ""}>成员</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>管理员</option></select></div><label class="check"><input name="disabled" type="checkbox" ${u.disabled ? "checked" : ""}>停用此用户</label><div class="notice">变更后该用户的会话将失效。最后一位有效管理员不可停用或降级。</div>${errorSlot()}<button class="primary">保存变更</button></form>`,
      { user: id },
    );
    return;
  }
  if (action === "audit") {
    const data = await api("/audit");
    modal(
      "我的操作记录",
      data
        .map(
          (r) =>
            `<div class="source-entry"><b class="small">${esc(r.action)}</b><p class="small muted">${esc(r.detail)}</p><span class="tiny muted">${date(r.created)}</span></div>`,
        )
        .join("") || '<p class="muted">暂无记录</p>',
    );
    return;
  }
}
function findArticles(raw) {
  const items = [],
    seen = new Set();
  function walk(v) {
    if (!v || typeof v !== "object") return;
    if (v.rest_id && typeof v.title === "string" && !seen.has(v.rest_id)) {
      seen.add(v.rest_id);
      items.push({ id: v.rest_id, title: v.title });
    }
    Object.values(v).forEach(walk);
  }
  walk(raw);
  return items;
}
async function handleForm(form, f, data, submitter) {
  const kind = form.dataset.form;
  if (kind === "keywords") {
    const body = {
      name: data.name,
      keywords: data.keywords
        .split("\n")
        .map((k) => k.trim())
        .filter(Boolean),
    };
    await api("/keyword-groups" + (S.modal.group ? "/" + S.modal.group : ""), {
      method: S.modal.group ? "PUT" : "POST",
      body,
    });
    closeModal();
    return navigate("keywords");
  }
  if (kind === "maintenance") {
    const body = {
      group_ids: f.getAll("group_ids"),
      enabled: f.has("enabled"),
      read_comments: f.has("read_comments"),
      read_home: f.has("read_home"),
    };
    for (const name of [
      "interval_minutes",
      "pages_per_cycle",
      "home_pages_per_cycle",
      "delay_min_seconds",
      "delay_max_seconds",
      "comment_pages",
    ])
      body[name] = Number(data[name]);
    await api("/accounts/" + S.modal.account + "/maintenance", {
      method: "PUT",
      body,
    });
    closeModal();
    toast("养护配置已保存");
    return navigate("maintenance");
  }
  if (kind === "global-search" || kind === "search") {
    if (data.kind === "detail" || (/^https?:\/\//.test(data.q) && postId(data.q))) return openPost(data.q);
    S.query = data.q;
    S.searchKind = data.kind || "search";
    S.product = data.product || "Latest";
    return navigate("explore");
  }
  if (kind === "account") {
    const a = await api("/accounts", { method: "POST", body: data });
    await refreshBase();
    S.account = a.id;
    localStorage.setItem("xapis-account", S.account);
    loginAccount(a.id);
    return;
  }
  if (kind === "account-login") {
    const body = {
      username: data.username,
      password: data.password,
      cookies: data.cookies,
      profile: data.profile.trim() ? JSON.parse(data.profile) : null,
    };
    const context = S.modal;
    context.busy = true;
    const progress = $(".login-progress", form),
      button = $("button.primary", form);
    const started = Date.now();
    let polling = false;
    progress.hidden = false;
    progress.classList.remove("failed");
    progress.textContent = "正在通过已绑定代理登录 X…";
    button.textContent = "正在登录并验证…";
    const timer = setInterval(async () => {
      if (polling || !form.isConnected) return;
      polling = true;
      try {
        const p = await api("/accounts/" + context.account + "/login-status");
        progress.textContent =
          p.message +
          " · 已等待 " +
          Math.floor((Date.now() - started) / 1000) +
          " 秒";
      } catch {
      } finally {
        polling = false;
      }
    }, 1500);
    try {
      await api("/accounts/" + context.account + "/login", {
        method: "POST",
        body,
      });
      form.reset();
      context.busy = false;
      S.account = context.account;
      localStorage.setItem("xapis-account", S.account);
      closeModal();
      await refreshBase();
      toast("X 账号已连接");
      await navigate("accounts");
    } catch (error) {
      progress.classList.add("failed");
      progress.textContent = error.message;
      toast(error.message);
      throw error;
    } finally {
      clearInterval(timer);
      button.textContent = "登录并验证";
      context.busy = false;
    }
    return;
  }
  if (kind === "proxy") {
    await api("/accounts/" + S.modal.account + "/proxy", {
      method: "PUT",
      body: data,
    });
    form.reset();
    closeModal();
    await refreshBase();
    toast("代理已更新，请重新登录");
    return navigate("accounts");
  }
  if (kind === "ai") {
    await api("/ai", { method: "PUT", body: data });
    form.elements.api_key.value = "";
    toast("AI 配置已保存");
    return navigate("settings");
  }
  if (kind === "source") {
    await api("/sources", { method: "POST", body: { ...data, enabled: true } });
    closeModal();
    toast("来源已添加，可点击立即采集");
    return navigate("sources");
  }
  if (kind === "rule") {
    data.source_ids = f.getAll("source_ids");
    data.enabled = f.has("enabled");
    data.interval_minutes = Number(data.interval_minutes);
    data.daily_limit = Number(data.daily_limit);
    await api("/rules" + (S.modal.rule ? "/" + S.modal.rule : ""), {
      method: S.modal.rule ? "PUT" : "POST",
      body: data,
    });
    closeModal();
    await refreshBase();
    return navigate("rules");
  }
  if (kind === "compose") {
    const context = S.modal;
    if (context.busy) throw new Error("请等待 AI 生成或媒体上传完成");
    const state = submitter?.value || "draft";
    const payload = {
      kind: data.kind,
      text: data.text,
      texts:
        data.kind === "thread"
          ? data.text
              .split(/\n\s*---\s*\n/)
              .map((t) => t.trim())
              .filter(Boolean)
          : [],
      title: data.title,
      media: context.media.map((m) => m.id),
      reply_to: data.reply_to,
      quote_url: data.quote_url,
      long: f.has("long"),
      article_id: data.article_id,
      publish_article: f.has("publish_article"),
      caption: data.caption,
      reply_mode: data.reply_mode,
      sources: context.sources,
    };
    context.busy = true;
    try {
      await api("/jobs" + (context.job ? "/" + context.job : ""), {
        method: context.job ? "PUT" : "POST",
        body: {
          account_id: data.account_id,
          request_id: context.request,
          payload,
          state,
          scheduled: data.scheduled
            ? new Date(data.scheduled).getTime() / 1000
            : null,
        },
      });
      context.busy = false;
      closeModal();
      S.jobFilter = state === "draft" ? "draft" : "queued";
      await refreshBase();
      toast(
        state === "draft"
          ? "草稿已保存"
          : "已加入发布队列，可在发布计划查看结果",
      );
      await navigate("jobs");
    } finally {
      context.busy = false;
    }
    return;
  }
  if (kind === "explorer") {
    if (!S.account) throw new Error("请先连接 X 账号");
    const params = { ...data };
    delete params.operation;
    if (params.user_ids) params.user_ids = JSON.parse(params.user_ids);
    Object.keys(params).forEach((k) => {
      if (params[k] === "") delete params[k];
    });
    const result = await api(`/accounts/${S.account}/explore`, {
      method: "POST",
      body: { operation: data.operation, params },
    });
    $("#explorer-result").innerHTML =
      `<pre class="mono">${esc(JSON.stringify(result, null, 2))}</pre>`;
    return;
  }
  if (kind === "chat-send") return sendChatMessage(data.text);
  if (kind === "chat-recipient") {
    const c = S.chat;
    const conversation = await api(`/accounts/${S.account}/chat/recipient?handle=${encodeURIComponent(data.handle)}`);
    if (S.chat !== c) return;
    c.inbox ||= {conversations:[],item_count:0};
    if (!c.inbox.conversations.some(t => t.id === conversation.id)) c.inbox.conversations.push(conversation);
    renderChatInbox();
    return openChatConversation(conversation.id);
  }
  if (kind === "chat-password") {
    const context = S.chat, account = S.account;
    const pin = data.pin;
    form.reset();
    await api(`/accounts/${account}/chat/password`, {method: "PUT", body: {pin}});
    if (S.chat !== context) return;
    S.chatVault?.dispose(); S.chatVault = null;
    Object.assign(context, {has_saved_pin: true, unlocked: false, messages: null, error: ""});
    renderChatSecurity(); renderChatInbox();
    toast("聊天密码已加密保存到 MySQL");
    return;
  }
  if (kind === "password") {
    await api("/auth/password", { method: "POST", body: data });
    form.reset();
    closeModal();
    S.chatVault?.dispose(); S.chatVault = null; S.chat = null;
    S.user = null;
    S.csrf = "";
    renderLogin(false);
    toast("密码已修改，请重新登录");
    return;
  }
  if (kind === "user") {
    await api("/users", { method: "POST", body: data });
    form.reset();
    closeModal();
    return navigate("settings");
  }
  if (kind === "edit-user") {
    await api("/users/" + S.modal.user, {
      method: "PATCH",
      body: { role: data.role, disabled: f.has("disabled") },
    });
    closeModal();
    if (S.user) await navigate("settings");
    return;
  }
}
setInterval(async () => {
  if (!S.user || document.hidden || $("#modal").open) return;
  const version = S.version;
  try {
    if (S.page === "jobs") {
      const jobs = await api("/jobs");
      if (version !== S.version) return;
      if (JSON.stringify(jobs) !== JSON.stringify(S.jobs)) {
        S.jobs = jobs;
        $("#view").innerHTML = jobsPage();
        S.stats = await api("/stats");
        widgets();
      }
    }
    if (S.page === "rules") {
      const rules = await api("/rules");
      if (version !== S.version) return;
      if (JSON.stringify(rules) !== JSON.stringify(S.rules)) {
        S.rules = rules;
        $("#view").innerHTML = rulesPage();
        S.stats = await api("/stats");
        widgets();
      }
    }
  } catch {}
}, 10000);
const policyDate = (ts) =>
  new Date(ts * 1000).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
function policyCard(account) {
  const p = account?.policy;
  if (!p) return "";
  const stage = {
    not_started: ["待首次登录", "gray"],
    warming: ["只读养护中", "orange"],
    limited: ["初期发布保护", "blue"],
    ready: ["常规运营", ""],
  }[p.stage];
  const details =
    p.stage === "not_started"
      ? `首次成功登录后开始 ${p.warmup_days} 天养护。`
      : p.stage === "warming"
        ? `X 写权限将于 ${policyDate(p.warmup_until)} 自动释放。`
        : `今日已用额度 ${p.today_used} 篇${p.daily_limit ? " / 上限 2 篇" : " · 已解除两篇限制"}。`;
  return `<div class="policy-card"><div class="row between">${badge(...stage)}<span class="tiny muted">${p.daily_limit ? "前 7 天每日 ≤ 2 篇" : "已满 7 天"}</span></div><p>${esc(details)}</p>${p.limit_until && p.daily_limit ? `<span class="tiny muted">两篇限制解除：${policyDate(p.limit_until)} · 北京时间</span>` : ""}</div>`;
}
function keywordsPage() {
  return `<div class="page-pad"><div class="page-intro"><div><h2>让浏览有方向</h2><p>每个目录是一组关键词，可绑定到多个账号进行只读养护。</p></div><button class="primary" data-action="add-keywords">${icon("plus")}新建分组</button></div>${S.groups.map((g) => `<div class="card"><div class="row between"><h3>${esc(g.name)}</h3>${badge(g.keywords.length + " 个关键词", "blue")}</div><div class="keyword-tags">${g.keywords.map((k) => `<span>${esc(k)}</span>`).join("")}</div><div class="actions"><button data-action="edit-keywords" data-id="${g.id}">编辑关键词</button><button class="danger" data-action="delete-keywords" data-id="${g.id}">删除分组</button></div></div>`).join("") || empty("从你的关注方向开始", "例如创建“AI 模型”“产品设计”分组，每行添加一个关键词，再绑定到账号。", "bookmark")}<div class="notice">养护可浏览首页推荐、搜索关键词和读取评论，不会关注、转发、点赞或回复。</div></div>`;
}
function maintenanceSummary() {
  const enabled = S.maintenance.filter(m => m.enabled && m.status === "connected").length;
  const reading = S.maintenance.reduce((total, m) => total + m.read_count, 0);
  const inProgress = S.maintenance.filter(m => m.running).length;
  return `<div class="summary-grid"><div class="summary-tile"><span>启用养护</span><strong>${enabled}<small> 个账号</small></strong></div><div class="summary-tile"><span>累计读取</span><strong>${fmt(reading)}<small> 条内容</small></strong></div><div class="summary-tile"><span>正在执行</span><strong>${inProgress}<small> 个步骤</small></strong></div></div>`;
}
function maintenanceCards() {
  return S.accounts.map(a => {
    const m = S.maintenance.find(m => m.account_id === a.id);
    const enabled = m?.enabled && a.status === "connected";
    const groupNames = (m?.group_ids || []).map(id => S.groups.find(g => g.id === id)?.name).filter(Boolean);
    return `<article class="card maintenance-card" data-account-id="${a.id}"><div class="account-card-head">${avatar(a.name, a.avatar)}<div class="grow"><h3>${esc(a.name)}</h3><p>${esc(a.handle ? "@" + a.handle : "等待登录")}</p></div>${badge(a.status !== "connected" ? "等待登录" : m?.running ? "正在读取" : enabled ? "按计划运行" : "已暂停", enabled ? "blue" : "gray")}</div>
      <div class="reading-sources"><span class="reading-source ${m?.read_home ? "enabled" : ""}">${icon("home")}首页推荐${m?.read_home ? ` · ${m.home_pages_per_cycle} 页` : " · 未启用"}</span><span class="reading-source ${groupNames.length ? "enabled" : ""}">${icon("search")}关键词${groupNames.length ? ` · ${m.pages_per_cycle} 页` : " · 未绑定"}</span></div>
      ${groupNames.length ? `<div class="keyword-tags">${groupNames.map(name => `<span>${esc(name)}</span>`).join("")}</div>` : ""}
      ${m ? `<div class="plan-grid"><div><span>每轮间隔</span><b>${m.interval_minutes} 分钟 ±20%</b></div><div><span>页间随机等待</span><b>${m.delay_min_seconds}～${m.delay_max_seconds} 秒</b></div><div><span>评论读取</span><b>${m.read_comments ? `每条最多 ${m.comment_pages} 页` : "关闭"}</b></div><div><span>Cookie 同步</span><b>${date(a.cookie_updated)}</b></div></div><div class="run-status"><div class="row between"><span>${m.running ? "当前正在执行" : "最近一次结果"}</span><small>${m.last_run ? date(m.last_run) : "尚未执行"}</small></div><p>${esc(m.running ? "正在通过代理读取 X，逐步结果可在执行日志中查看。" : m.last_result || "任务就绪，等待调度")}</p><div class="next-run">${icon("clock")}<span>${enabled ? m.running ? "当前页完成后安排下一步" : `下次读取 ${date(m.next_run)}` : "已暂停自动读取"}</span><b>已读 ${fmt(m.read_count)} 条</b></div></div>` : '<p class="muted">登录后可配置首页推荐、关键词和读取节奏。</p>'}
      <details class="policy-details"><summary>${icon("shield")}${a.policy?.can_write === false ? "只读保护生效中" : "账号发布保护规则"}</summary>${policyCard(a)}</details>
      <div class="actions"><button class="primary" data-action="maintenance-logs" data-id="${a.id}">${icon("code")}执行日志</button><button class="secondary" data-action="configure-maintenance" data-id="${a.id}">养护配置</button>${enabled ? `<button class="text-btn" data-action="maintenance-run" data-id="${a.id}" ${m.running ? "disabled" : ""}>运行一轮</button><button class="text-btn muted" data-action="maintenance-pause" data-id="${a.id}">暂停</button>` : ""}</div></article>`;
  }).join("") || empty("先连接一个账号", "绑定代理并登录后，即可开始只读养护。", "users", "添加账号", "add-account");
}
function maintenancePage() {
  return `<div class="page-pad workspace-page"><div class="page-intro"><div><div class="eyebrow">ACCOUNT CARE</div><h2>让浏览按计划进行</h2><p>首页推荐与关键词搜索，统一管理读取节奏和执行记录。</p></div><button class="secondary" data-page="keywords">${icon("bookmark")}关键词目录</button></div><div id="maintenance-summary">${maintenanceSummary()}</div><div id="maintenance-cards">${maintenanceCards()}</div><div class="footnote">${icon("shield")}<span>养护始终只读，不关注、不点赞、不转发、不回复。默认前 4 天禁止写入；满 7 天解除每日两篇限制。当前页面每 10 秒更新运行状态。</span></div></div>`;
}
function startMaintenanceRefresh(version) {
  let signature = JSON.stringify([S.maintenance, S.accounts]);
  async function refresh() {
    if (version !== S.version || S.page !== "maintenance") return;
    if (!$("#modal").open && !document.hidden) {
      try {
        const [tasks, accounts] = await Promise.all([api("/maintenance"), api("/accounts")]);
        if (version !== S.version) return;
        const updated = JSON.stringify([tasks, accounts]);
        S.maintenance = tasks; S.accounts = accounts;
        if (updated !== signature) {
          signature = updated;
          const expanded = new Set([...document.querySelectorAll(".maintenance-card .policy-details[open]")].map(el => el.closest(".maintenance-card").dataset.accountId));
          const focus = document.activeElement?.closest("#maintenance-cards button")?.dataset;
          $("#maintenance-summary").innerHTML = maintenanceSummary();
          $("#maintenance-cards").innerHTML = maintenanceCards();
          document.querySelectorAll(".maintenance-card").forEach(card => { card.querySelector(".policy-details").open = expanded.has(card.dataset.accountId); });
          if (focus) [...document.querySelectorAll("#maintenance-cards button")].find(el => el.dataset.action === focus.action && el.dataset.id === focus.id)?.focus({preventScroll: true});
        }
      } catch { /* A transient poll failure must not replace the current page. */ }
    }
    if (version === S.version) S.maintenanceTimer = setTimeout(refresh, 10000);
  }
  S.maintenanceTimer = setTimeout(refresh, 10000);
}
function maintenanceForm(a, m) {
  return `<form data-form="maintenance" class="structured-form"><section class="form-section"><div class="section-heading"><span class="step-number">1</span><div><h3>选择浏览来源</h3><p>每轮先浏览首页推荐，再搜索已绑定的关键词。</p></div></div><label class="option-card"><input type="checkbox" name="read_home" ${m.read_home ? "checked" : ""}><span><b>首页推荐时间线</b><small>读取当前账号主页收到的推荐贴文</small></span>${icon("home")}</label>${field("首页推荐最多读取页数", "home_pages_per_cycle", "", "number", m.home_pages_per_cycle, 'required min="1" max="10"')}<div class="field"><label>关键词分组</label><div class="source-picks">${S.groups.map(g => `<label class="check"><input type="checkbox" name="group_ids" value="${g.id}" ${m.group_ids.includes(g.id) ? "checked" : ""}>${esc(g.name)}<span class="muted">${g.keywords.length} 词</span></label>`).join("") || '<p class="small muted">尚未创建分组，可先开启首页推荐养护。</p>'}</div></div>${field("关键词搜索最多读取页数", "pages_per_cycle", "", "number", m.pages_per_cycle, 'required min="1" max="10"')}</section><section class="form-section"><div class="section-heading"><span class="step-number">2</span><div><h3>设置读取节奏</h3><p>翻页和来源切换都遵守随机等待。</p></div></div>${field("每轮间隔（分钟，随机 ±20%）", "interval_minutes", "", "number", m.interval_minutes, 'required min="15" max="1440"')}<div class="fields">${field("随机等待最少（秒）", "delay_min_seconds", "", "number", m.delay_min_seconds, 'required min="5" max="600"')}${field("随机等待最多（秒）", "delay_max_seconds", "", "number", m.delay_max_seconds, 'required min="5" max="1800"')}</div><label class="option-card"><input type="checkbox" name="read_comments" ${m.read_comments ? "checked" : ""}><span><b>抽样查看评论</b><small>每页选择一条贴文，只读其评论，不发送回复</small></span>${icon("reply")}</label>${field("每条贴文最多读取评论页数", "comment_pages", "", "number", m.comment_pages, 'required min="1" max="5"')}</section><section class="form-section"><label class="option-card"><input type="checkbox" name="enabled" ${m.enabled ? "checked" : ""}><span><b>启用定时养护</b><small>首次登录后的保护周期不受此开关影响</small></span>${icon("clock")}</label><details class="policy-details"><summary>查看账号保护规则</summary>${policyCard(a)}</details></section>${errorSlot()}<div class="form-footer"><span class="tiny muted">保存后按新配置开始下一轮</span><button class="primary">保存配置</button></div></form>`;
}

function keywordsForm(group) {
  modal(
    group ? "编辑关键词目录" : "新建关键词目录",
    `<form data-form="keywords">${field("分组名称", "name", "例如：AI 模型与研究", "text", group?.name || "", 'required maxlength="100"')}${textarea("关键词（每行一个）", "keywords", group?.keywords.join("\n") || "", "人工智能\n大语言模型\nAI research", "required")}<div class="notice">支持 X 搜索语法，每组最多 100 个关键词，每个最多 200 字符。</div>${errorSlot()}<button class="primary">保存分组</button></form>`,
    { group: group?.id },
  );
}
async function maintenanceAction(action, id) {
  if (action === "add-keywords") {
    keywordsForm();
    return;
  }
  if (action === "edit-keywords") {
    keywordsForm(S.groups.find((g) => g.id === id));
    return;
  }
  if (action === "delete-keywords") {
    return confirmAction(
      "删除关键词分组",
      "已绑定账号的分组需要先解除绑定。",
      "delete-keywords",
      { group: id },
    );
  }
  if (action === "confirm-delete-keywords") {
    await api("/keyword-groups/" + S.modal.group, { method: "DELETE" });
    closeModal();
    return navigate("keywords");
  }
  if (action === "maintenance-run" || action === "maintenance-pause") {
    await api(
      "/accounts/" +
        id +
        "/maintenance/" +
        (action === "maintenance-run" ? "run" : "pause"),
      { method: "POST" },
    );
    toast(
      action === "maintenance-run"
        ? "已安排读取；翻页随机间隔不会被跳过"
        : "养护任务已暂停",
    );
    return navigate("maintenance");
  }
  if (action === "maintenance-logs") {
    return showMaintenanceLogs(id);
  }
  if (action === "configure-maintenance") {
    [S.groups, S.maintenance] = await Promise.all([
      api("/keyword-groups"),
      api("/maintenance"),
    ]);
    const a = S.accounts.find((a) => a.id === id),
      m = S.maintenance.find((m) => m.account_id === id) || {
        group_ids: [],
        enabled: true,
        interval_minutes: 60,
        pages_per_cycle: 3,
        read_home: true,
        home_pages_per_cycle: 2,
        delay_min_seconds: 30,
        delay_max_seconds: 90,
        read_comments: true,
        comment_pages: 2,
      };
    modal(
      "养护配置 · " + a.name,
      maintenanceForm(a, m),
      { account: id },
    );
  }
}

function logTime(value) {
  return value ? new Date(value * 1000).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", hour12: false}) : "—";
}
function cookieSyncText(sync) {
  if (!sync) return "Cookie 同步结果未记录";
  const names = (v) => (v || []).join("、") || "无";
  if (sync.status === "applied") return `Cookie 已加密写入 MySQL · ${logTime(sync.saved_at)}；接收 ${names(sync.updated)}；值变化 ${names(sync.changed)}；删除 ${names(sync.removed)}`;
  return {no_set_cookie: "X 未下发新的 Set-Cookie，本次无需更新数据库", not_applied: "公开素材请求，Cookie 不写入账号会话", stale_session: "会话版本已变化，跳过旧请求的 Cookie", ignored: "收到 Set-Cookie，但没有可应用的 X Cookie", failed: "Cookie 写入失败：" + (sync.error_type || "未知错误"), unreported: "Cookie 回调未返回写入结果"}[sync.status] || "Cookie 同步结果未知";
}
function maintenanceLogCard(l) {
  const d = l.details || {},
    labels = {ok: "完成", error: "失败", running: "执行中", warning: "部分错误", interrupted: "曾中断"},
    operations = {home: "首页推荐", search: "关键词搜索", comments: "评论读取", viewer: "身份保活", new_cycle: "下一轮"},
    reasons = {next_page: "页间随机等待", cycle_interval: "轮次随机间隔", error_backoff: "失败后退避", rate_limit: "限流后退避", account_expired: "会话失效，任务已停用"},
    stops = {page_limit: "达到本轮页数上限", no_cursor: "X 未返回下一页游标", repeated_cursor: "游标重复，停止继续翻页"};
  const cursor = (c) => c?.present ? `有 · ${c.fingerprint}` : "无";
  return `<article class="maintenance-log"><div class="row between"><strong>${esc(l.keyword || (l.operation === "home" || d.source === "home" ? "首页推荐" : "会话保活"))}</strong>${badge(labels[l.status] || l.status, l.status === "ok" ? "" : l.status === "running" ? "blue" : l.status === "error" ? "red" : "orange")}</div><p>${esc(l.message)}</p><div class="tiny muted">${logTime(l.created)} · ${operations[l.operation] || esc(l.operation)}${l.operation === "viewer" ? "" : ` · 第 ${l.page} 页`} · ${l.item_count} 条${d.duration_ms != null ? ` · ${d.duration_ms} ms` : ""}</div>${d.step_id ? `<div class="trace-summary">${d.identity_verified ? "<div>绑定账号身份验证通过</div>" : ""}${d.cursor_out ? `<div>游标：${cursor(d.cursor_in)} → ${cursor(d.cursor_out)}</div>` : ""}${d.stop_reason ? `<div>${stops[d.stop_reason] || esc(d.stop_reason)}</div>` : ""}${d.delay_seconds != null ? `<div>${reasons[d.delay_reason] || "等待"}：<b>${d.delay_seconds} 秒</b>${d.delay_range_seconds ? `（范围 ${d.delay_range_seconds.join("～")} 秒）` : ""}</div><div>下次执行：${logTime(d.next_run)} · ${operations[d.next_operation] || "下一轮"}</div>` : ""}${d.since_previous_step_seconds != null ? `<div>距上步完成 ${d.since_previous_step_seconds} 秒 · 调度延后 ${d.scheduler_lag_seconds} 秒</div>` : ""}</div><details data-log-details="${l.id}"><summary>逐步请求、Cookie 同步与实际结果（${d.requests?.length || 0} 次请求）</summary>${(d.requests || []).map((r) => `<div class="trace-request"><b>${esc(r.method)} ${r.status ?? (l.status === "running" ? "等待响应" : "未收到响应")}</b> <span class="tiny muted">${r.duration_ms != null ? r.duration_ms + " ms" : ""}</span><p class="log-path">${esc(r.path)}</p><p class="small">${esc(cookieSyncText(r.checks?.cookie_sync_result))}</p>${r.checks?.csrf_matches_cookie != null ? `<div class="tiny">CSRF 与 Cookie：${r.checks.csrf_matches_cookie ? "一致" : "不一致"}</div>` : ""}${r.result?.errors?.length || r.result?.error_excerpt ? `<pre class="mono">${esc(JSON.stringify(r.result, null, 2))}</pre>` : `<span class="tiny muted">响应 ${r.result?.bytes ?? "—"} 字节${r.result?.data_present ? " · 包含数据" : ""}</span>`}</div>`).join("")}${d.error ? `<pre class="mono">${esc(JSON.stringify(d.error, null, 2))}</pre>` : ""}<details data-log-details="raw-${l.id}"><summary>完整诊断数据（脱敏）</summary><pre class="mono">${esc(JSON.stringify(d, null, 2))}</pre></details></details>` : '<p class="tiny muted">历史摘要；此记录生成时尚未启用逐步诊断。</p>'}</article>`;
}
async function showMaintenanceLogs(id) {
  const context = {maintenanceLogs: id};
  modal("养护执行日志", '<div class="notice">每 5 秒更新；仅刷新本地日志，不会触发 X 请求。时间为北京时间。Cookie 值和完整游标不展示。</div><div id="maintenance-log-status" class="tiny muted"></div><div id="maintenance-log-list"></div>', context);
  async function refreshLogs() {
    if (S.modal !== context || !$("#modal").open) return;
    try {
      const logs = await api("/accounts/" + id + "/maintenance/logs");
      if (S.modal !== context || !$("#modal").open) return;
      const list = $("#maintenance-log-list"), body = $(".modal-body", $("#modal")), top = body.scrollTop;
      const opened = new Set([...list.querySelectorAll("details[open]")].map((e) => e.dataset.logDetails));
      list.innerHTML = logs.map(maintenanceLogCard).join("") || '<p class="muted">尚无养护记录</p>';
      list.querySelectorAll("details").forEach((e) => { e.open = opened.has(e.dataset.logDetails); });
      body.scrollTop = top;
      $("#maintenance-log-status").textContent = "已更新：" + logTime(Date.now() / 1000);
    } catch (e) {
      if (S.modal === context && $("#maintenance-log-status")) $("#maintenance-log-status").textContent = "日志更新失败：" + e.message;
    }
    if (S.modal === context && $("#modal").open) setTimeout(refreshLogs, 5000);
  }
  await refreshLogs();
}

function updateComposePermissions() {
  const form = $("#compose-form");
  if (!form) return;
  const a = S.accounts.find((a) => a.id === form.elements.account_id.value),
    p = a?.policy;
  const scheduled = form.elements.scheduled.value
    ? new Date(form.elements.scheduled.value).getTime() / 1000
    : Date.now() / 1000;
  const blocked =
    a?.status !== "connected" ||
    (p?.warmup_until && scheduled < p.warmup_until);
  const publish = form.querySelector('button[value="queued"]');
  publish.disabled = Boolean(blocked);
  publish.title = blocked
    ? "账号尚未登录或仍在只读养护期，可先保存草稿"
    : "提交到发布队列";
  $("#media-files").disabled =
    a?.status !== "connected" || p?.can_write === false;
}

function newRequestId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

// Poll only while this unlocked view is visible and idle. Never auto-unlock or retry a send.
setInterval(async () => {
  const c = S.chat;
  if (document.hidden || S.page !== "messages" || !c?.unlocked || c.busy || c.sending || c.inboxLoading || c.threadLoading || document.activeElement?.closest("#chat-inbox form") || $("#chat-text")?.value) return;
  try { await refreshChatInbox(); if (S.chat === c && c.selected) await openChatConversation(c.selected); } catch {}
},30000);
