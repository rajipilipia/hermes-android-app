// Real installed renderer and CSS. Hidden DOM copies only; no app state,
// preferences, approval policy, keyboard, native input or chat send is changed.
// ANDROID_STATUSBAR_CDP=http://127.0.0.1:<owned-forward> node tests/browser/statusbar-space.mjs
import { writeFileSync, mkdirSync } from "node:fs";
export function statusbarSpaceCase({ width, name, project = "hermes-agent" }) {
  const live = document.querySelector('footer[data-slot="statusbar"]');
  if (!live) throw new Error("Status bar missing; stop at sign-in");
  const f = live.cloneNode(true);
  f.setAttribute("aria-hidden", "true");
  f.style.cssText = `position:fixed;visibility:hidden;left:0;top:-1000px;width:${width}px`;
  for (const e of f.querySelectorAll("[id]")) e.removeAttribute("id");
  try {
    const left = f.children[0], right = f.children[1];
    const approval = right.querySelector("button");
    if (!approval) throw new Error("Approval control missing");
    approval.querySelector("span").textContent = "Smart";
    const picker = f.querySelector('[data-slot="profile-switcher"]');
    const label = picker.querySelector('[data-android-profile-prefix]') ?? picker.querySelector("button>span>span:last-child");
    if (name) {
      if (label.hasAttribute("data-android-profile-prefix")) {
        label.dataset.androidProfilePrefix = Array.from(name).slice(0, 8).join("") + (Array.from(name).length > 8 ? "…" : "");
        label.firstElementChild.textContent = name;
      } else label.textContent = name;
    }
    for (const [id, text] of [["gateway-health", "Backend ready"], ["workspace-cwd", project]]) {
      let item = left.querySelector(`[data-android-statusbar-item="${id}"]`);
      if (!item) { item = approval.cloneNode(true); item.dataset.androidStatusbarItem = id; left.append(item); }
      item.querySelector("span").textContent = text;
    }
    document.body.append(f);
    const rect = f.getBoundingClientRect();
    const items = [...left.children, ...right.children].map(e => ({text:e.textContent, left:e.getBoundingClientRect().left, right:e.getBoundingClientRect().right}));
    const value = label.firstElementChild ?? label;
    const text = value.firstChild;
    const prefix = Array.from(value.textContent).slice(0, 8).join("");
    const range = document.createRange(); range.setStart(text, 0); range.setEnd(text, prefix.length);
    // Measure inside the real text node's font context, not the footer font.
    // The ellipsis needs its own room after the protected eight characters.
    const probe = document.createElement("span");
    probe.textContent = prefix + (Array.from(value.textContent).length > 8 ? "…" : "");
    probe.style.cssText = "position:absolute;white-space:pre";
    value.append(probe);
    const required = probe.getBoundingClientRect().width;
    probe.remove();
    const visible = label.getBoundingClientRect().width;
    const smart = approval.querySelector("span"), smartRange = document.createRange(); smartRange.selectNodeContents(smart);
    const smartBox = smartRange.getBoundingClientRect();
    const failures = [];
    if (items.some(e => e.right > rect.right + 0.5 || e.left < rect.left - 0.5)) failures.push("item exceeds footer");
    if (visible + 0.5 < required) failures.push("profile first eight characters clipped");
    if (smartBox.right > right.getBoundingClientRect().right + 0.5) failures.push("Smart clipped by group");
    if (f.scrollHeight > f.clientHeight + 1 || f.scrollWidth > f.clientWidth + 1) failures.push("footer scrolls");
    if (rect.width - f.clientWidth > 1) failures.push("vertical scrollbar steals width");
    return {width, name:value.textContent, required, visible, items, smartRight:smartBox.right, groupRight:right.getBoundingClientRect().right, clientWidth:f.clientWidth, scrollWidth:f.scrollWidth, failures};
  } finally { f.remove(); }
}
if (process.env.ANDROID_STATUSBAR_CDP) {
  const endpoint = process.env.ANDROID_STATUSBAR_CDP;
  const url = new URL(endpoint); if (url.hostname !== "127.0.0.1") throw new Error("Loopback CDP only");
  const pages = (await (await fetch(`${endpoint}/json/list`)).json()).filter(t => t.type === "page");
  if (pages.length !== 1) throw new Error("Require the exact app WebView, not a guest");
  const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
  let id = 0;
  const evaluate = expression => new Promise((ok, bad) => {
    const rid = ++id;
    const handler = ev => { const r = JSON.parse(ev.data); if(r.id !== rid)return; ws.removeEventListener("message", handler); if(r.error || r.result.exceptionDetails)bad(new Error(JSON.stringify(r))); else ok(r.result.result.value); };
    ws.addEventListener("message", handler); ws.send(JSON.stringify({id:rid,method:"Runtime.evaluate",params:{expression,returnByValue:true}}));
  });
  const cases = [{width:443}, {width:443,name:"default"}, {width:443,name:"WWWWWWWW-long-name"}, {width:360,name:"abcdefgh-long-profile",project:"a-very-long-project-folder-name"}];
  const results = [];
  try { for(const c of cases)results.push(await evaluate(`(${statusbarSpaceCase.toString()})(${JSON.stringify(c)})`)); }
  finally { ws.close(); }
  const dir = ".cache/statusbar-space"; mkdirSync(dir,{recursive:true}); writeFileSync(`${dir}/browser-results.json`,JSON.stringify(results,null,2));
  const failures = results.flatMap(r=>r.failures);
  console.log(JSON.stringify({cases:results.length,failures,proof:`${dir}/browser-results.json`}));
  if(failures.length)process.exitCode=1;
}
