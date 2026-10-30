// Private keys are confined to this worker. Only display-ready messages leave it.
import {sendPayload, keyPayload, messageView} from "./chat-protocol.mjs";
const nativeFetch = globalThis.fetch.bind(globalThis);
let session = null, cryptoChat = null, context = null, busy = false, phase = "";
const toBase64 = bytes => {
  let s = "";
  for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(s);
};
const fromBase64 = text => Uint8Array.from(atob(text), c => c.charCodeAt(0));

async function api(path, method = "GET", body) {
  const response = await nativeFetch(`/api/accounts/${session.account}/chat/${path}`, {
    method, credentials: "same-origin", headers: {"X-Requested-With": "XApis", "X-CSRF-Token": session.csrf, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw new Error(value.detail || "聊天服务请求失败");
  }
  return response.json();
}

globalThis.fetch = async (input, init) => {
  const request = new Request(input, init);
  const url = new URL(request.url);
  if (url.origin === self.location.origin) return nativeFetch(request);
  if (!session || !context) throw new Error("Chat relay is not initialized");
  const headers = Object.fromEntries(request.headers);
  const response = await api("relay", "POST", {
    context_id: context.context_id, url: url.href, method: request.method, headers,
    body: toBase64(new Uint8Array(await request.arrayBuffer())),
  });
  return new Response(fromBase64(response.body), {status: response.status, headers: {"content-type": response.content_type}});
};

function errorMessage(error) {
  const message = String(error?.message || "");
  const guesses = message.match(/reason=InvalidPin guesses_remaining=(\d+)/);
  if (guesses) return {code: "invalid_pin", message: `聊天密码不正确，剩余 ${guesses[1]} 次机会；不会自动重试。`, guesses_remaining: Number(guesses[1])};
  if (/NotRegistered/.test(message)) return {code: "not_registered", message: "当前 X 聊天密钥尚未完成备份，请在 X Chat 检查初始化状态。"};
  if (/InvalidAuth/.test(message)) return {code: "invalid_auth", message: "密钥恢复授权已失效，请刷新 X 登录会话后重试。"};
  if (/UpgradeRequired/.test(message)) return {code:"protocol_version",message:"密钥恢复协议版本不兼容，请更新聊天组件。"};
  if (/RateLimit/.test(message)) return {code: "rate_limit", message: "密钥服务暂时限流，请稍后手动重试。"};
  if (/^X |^请|^聊天|^不允许|^账号|^会话|^群聊/.test(message)) return {code: "chat_error", message: message.slice(0, 180)};
  if (/Transient|fetch|network|relay/i.test(message)) return {code: "network", message: "聊天密钥服务连接失败，请检查账号代理；未自动重试密码。"};
  const diagnostic = message.replace(/[A-Za-z0-9+/_=.-]{24,}/g, "[redacted]").replace(/\b\d{4,}\b/g, "[value]").replace(/\[(?:\s*\d{1,3}\s*,){8,}[^\]]*\]/g, "[bytes]").slice(0, 220);
  return {code: "unlock_failed", message: "聊天解锁未完成，请检查密码、X 登录状态和代理。", diagnostic: `${phase} · ${error?.name || "Error"} · ${diagnostic}`};
}

async function signingKeys(participants) {
  const ids = [...new Set([context.user_id, ...(participants || [])])].filter(id => /^\d{1,30}$/.test(id)).slice(0,100);
  const keys = await api("public-keys?ids=" + encodeURIComponent(ids.join(",")));
  cryptoChat.setSigningKeys(keys);
  return keys;
}

self.onmessage = async ({data}) => {
  if (busy) { self.postMessage({id: data.id, error: {message: "正在处理上一个聊天步骤"}}); return; }
  busy = true;
  try {
    if (data.type === "unlock") {
      session = {account: data.account, csrf: data.csrf};
      phase = "读取密钥配置";
      self.postMessage({progress: "正在读取聊天密钥备份配置"});
      context = await api("unlock-context", "POST");
      const pin = new TextEncoder().encode(context.pin);
      delete context.pin;
      try {
        phase = "加载加密组件";
        self.postMessage({progress: "正在载入浏览器加密组件"});
        const {createChat} = await import("./vendor/chat-sdk.mjs");
        cryptoChat = await createChat({juiceboxConfig: JSON.stringify(context.config),
          getAuthToken: async id => {
            const token = context.realm_tokens[String(id).toLowerCase().replaceAll("-", "")];
            if (!token) throw new Error("聊天密钥恢复授权不完整");
            return token;
          }});
        phase = "恢复聊天密钥";
        self.postMessage({progress: "正在验证已保存的聊天密码并恢复密钥"});
        await cryptoChat.unlock(pin);
        phase = "校验账号公钥";
        const own = context.public_keys.find(k => k.publicKeyVersion === context.version);
        if (!own || !cryptoChat.matchesRegisteredKey(own.identityPublicKey)) throw new Error("聊天密钥与当前绑定账号不一致");
        cryptoChat.setIdentity({userId:context.user_id,signingKeyVersion:context.version});
        cryptoChat.setSigningKeys(context.public_keys);
        cryptoChat.setCacheKeys(true);
        cryptoChat.setRejectUnverified(true);
        self.postMessage({id: data.id, result: {unlocked: cryptoChat.isUnlocked(), context_id: context.context_id}});
      } finally { pin.fill(0); }
    } else if (data.type === "decrypt") {
      if (!cryptoChat?.isUnlocked()) throw new Error("请先解锁聊天");
      await signingKeys(data.participants);
      const decoded = cryptoChat.decryptEvents({events:data.events || []});
      const event_types = decoded.messages.map(m => m.event?.type || "missing");
      const errors = Object.values(decoded.errors || {}).map(v => String(v).replace(/[A-Za-z0-9+/_=.-]{24,}/g, "[redacted]").replace(/\b\d{4,}\b/g, "[value]").slice(0, 160));
      self.postMessage({id: data.id, result: {...messageView(decoded, data.page_events),
        diagnostic: errors.length ? JSON.stringify({event_types, errors}) : ""}});
    } else if (data.type === "send") {
      if (!cryptoChat?.isUnlocked()) throw new Error("请先解锁聊天");
      const status = await api("status");
      if (!status.can_write) throw new Error("账号仍处于只读养护期，不能发送私信");
      if (typeof data.text !== "string" || !data.text.trim() || data.text.length > 10000) throw new Error("请输入 1–10000 字的聊天内容");
      const keys = await signingKeys(data.participants);
      const page = await api("conversations/" + encodeURIComponent(data.conversation));
      let prepared = null;
      try {
        if (page.events.length) {
          const decoded = cryptoChat.decryptEvents({events:page.events});
          if (Object.keys(decoded.errors || {}).length) throw new Error("会话事件未通过完整验证，请先刷新会话核对，暂不发送");
        } else {
          if (page.has_more) throw new Error("会话尚有历史事件，请先恢复原会话密钥");
          if (!/^\d+:\d+$/.test(data.conversation)) throw new Error("群聊需要先恢复已有会话密钥");
          const ids = [...new Set(data.conversation.split(":"))];
          if (!ids.includes(context.user_id) || ids.some(id => !keys.some(k => k.userId === id))) throw new Error("聊天成员尚未提供可用的加密公钥");
          prepared = cryptoChat.prepareConversationKeyChange({conversationId:data.conversation,
            publicKeys:keys.filter(k => ids.includes(k.userId)).map(k => ({userId:k.userId,publicKey:k.identityPublicKey,keyVersion:k.publicKeyVersion}))});
          await api("conversation-keys", "POST", keyPayload(prepared));
        }
        const payload = cryptoChat.encryptMessage({conversationId:data.conversation,text:data.text,
          ...(prepared ? {conversationKey:prepared.conversationKey,conversationKeyVersion:prepared.conversationKeyVersion} : {})});
        const result = await api("send", "POST", sendPayload(data.conversation,payload));
        const decoded = {messages:result.events.map(eventB64 => ({originalB64:eventB64,
          event:cryptoChat.decryptEvent({eventB64,
            ...(prepared ? {conversationKeys:{[prepared.conversationKeyVersion]:prepared.conversationKey}} : {})})})),errors:{}};
        const failure = decoded.messages.find(m => m.event.type === "failure");
        if (failure) throw new Error("X 拒绝了这条私信：" + String(failure.event.failure || "unknown"));
        const view = messageView(decoded);
        if (!view.messages.some(m => m.id === payload.messageId)) throw new Error("X 返回了事件，但暂未确认消息送达；请刷新会话核对，不要重复发送");
        self.postMessage({id:data.id,result:{...view,confirmed:true}});
      } finally { prepared?.conversationKey?.fill(0); }
    } else if (data.type === "lock") {
      cryptoChat?.free(); cryptoChat = null;
      if (context) await api("unlock-context/" + context.context_id, "DELETE").catch(() => {});
      context = null;
      self.postMessage({id: data.id, result: {unlocked: false}});
    } else throw new Error("不支持此聊天操作");
  } catch (error) {
    if (data.type === "unlock") {
      cryptoChat?.free(); cryptoChat = null;
      if (context) await api("unlock-context/" + context.context_id, "DELETE").catch(() => {});
      context = null;
    }
    self.postMessage({id: data.id, error: errorMessage(error)});
  } finally { busy = false; }
};
