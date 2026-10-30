export class ChatVault {
  constructor(account, csrf, progress) {
    this.account = account; this.csrf = csrf; this.pending = new Map(); this.serial = 0;
    this.worker = new Worker(new URL("./chat-worker.mjs", import.meta.url), {type: "module"});
    this.worker.onmessage = ({data}) => {
      if (data.progress) { progress(data.progress); return; }
      const task = this.pending.get(data.id);
      if (!task) return;
      this.pending.delete(data.id); clearTimeout(task.timeout);
      if (data.error) {
        const error = new Error(data.error.message);
        error.diagnostic = data.error.diagnostic;
        task.reject(error);
      } else task.resolve(data.result);
    };
    this.worker.onerror = () => this.fail("浏览器加密组件未能启动，请刷新页面后重试。");
  }
  fail(message) {
    for (const task of this.pending.values()) { clearTimeout(task.timeout); task.reject(new Error(message)); }
    this.pending.clear();
  }
  request(type, value = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.serial;
      const timeout = setTimeout(() => { this.dispose(); reject(new Error("聊天请求超时，未自动重试密码。")); }, 120000);
      this.pending.set(id, {resolve, reject, timeout});
      this.worker.postMessage({id, type, ...value});
    });
  }
  unlock() { return this.request("unlock", {account: this.account, csrf: this.csrf}); }
  decrypt(events, participants, page_events) { return this.request("decrypt", {events, participants, page_events}); }
  send(conversation,text,participants) { return this.request("send",{conversation,text,participants}); }
  async lock() { try { await this.request("lock"); } finally { this.dispose(); } }
  dispose() { this.fail("聊天已锁定"); this.worker.terminate(); }
}
