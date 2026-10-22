// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  installSignInControl,
  observePcAuth,
} from "../src/desktop/auth-control";
afterEach(() => {
  document.body.replaceChildren();
});
it("observes a native sign-in-required ticket result without retry, persistence or automatic sign-in", async () => {
  const auth = {
    signIn: vi.fn(async () => {}),
    ticket: vi.fn(async () => "fresh"),
    signOut: vi.fn(),
  };
  const control = { requireSignIn: vi.fn(), authenticated: vi.fn() };
  const observed = observePcAuth(auth, control);
  auth.ticket.mockRejectedValueOnce(
    Object.assign(new Error("Sign in again"), { name: "PcSignInRequired" }),
  );
  await expect(observed.ticket()).rejects.toThrow("Sign in again");
  expect(control.requireSignIn).toHaveBeenCalledOnce();
  expect(auth.signIn).not.toHaveBeenCalled();
  expect(auth.ticket).toHaveBeenCalledTimes(1);
  await expect(observed.ticket()).resolves.toBe("fresh");
  expect(control.authenticated).toHaveBeenCalledOnce();
});
it("offers native sign-in only after a ticket failure and never signs in or resends automatically", async () => {
  const auth = {
    signIn: vi.fn(async () => {}),
    ticket: vi.fn(async () => ""),
    signOut: vi.fn(),
  };
  const restart = vi.fn();
  const control = installSignInControl({
    auth,
    restart,
    nativeAvailable: true,
  });
  expect(document.querySelector("button")).toBeNull();
  control.requireSignIn();
  const button = document.querySelector("button");
  expect(button).not.toBeNull();
  expect(button!.textContent).toBe("Sign in to this PC");
  expect(auth.signIn).not.toHaveBeenCalled();
  button!.click();
  await vi.waitFor(() => expect(restart).toHaveBeenCalledOnce());
  expect(auth.signIn).toHaveBeenCalledOnce();
  expect(auth.ticket).not.toHaveBeenCalled();
  control.dispose();
  expect(document.querySelector("button")).toBeNull();
});
it("authenticated native control offers explicit local sign-out; disposal is not logout", async () => {
 const auth={signIn:vi.fn(async()=>{}),ticket:vi.fn(async()=>"fresh"),signOut:vi.fn()};const restart=vi.fn();
 const control=installSignInControl({auth,restart,nativeAvailable:true});
 control.authenticated();control.authenticated();
 const settings=document.createElement('div');document.body.append(settings);control.mountSettings(settings);
 const buttons=[...document.querySelectorAll("button")];
 expect(buttons).toHaveLength(1);expect(buttons[0].textContent).toBe("Sign out of this PC");
 expect(auth.signOut).not.toHaveBeenCalled();buttons[0].click();expect(auth.signOut).toHaveBeenCalledOnce();await vi.waitFor(()=>expect(restart).toHaveBeenCalledOnce());
 control.dispose();expect(auth.signOut).toHaveBeenCalledOnce();
});
it("keeps authenticated sign-out out of the chat overlay and mounts it only inside Settings", () => {
 const auth={signIn:vi.fn(async()=>{}),ticket:vi.fn(async()=>"fresh"),signOut:vi.fn(async()=>{})};
 const control=installSignInControl({auth,restart:vi.fn(),nativeAvailable:true});
 control.authenticated();
 expect(document.querySelector('.hermes-android-signin')).toBeNull();
 expect(document.body.textContent).not.toContain('Sign out of this PC');
 const settings=document.createElement('div');document.body.append(settings);
 const unmount=control.mountSettings(settings);
 expect(settings.querySelector('button')?.textContent).toBe('Sign out of this PC');
 unmount();expect(settings.querySelector('button')).toBeNull();
 expect(auth.signOut).not.toHaveBeenCalled();control.dispose();
});
it("does not reload before native logout acknowledgement; cleanup failure stays visible without automatic retry", async () => {
 let resolve!:()=>void;let reject!:(error:Error)=>void;
 const auth={signIn:vi.fn(async()=>{}),ticket:vi.fn(async()=>"fresh"),signOut:vi.fn(()=>new Promise<void>((ok,no)=>{resolve=ok;reject=no;}))};const restart=vi.fn();
 const control=installSignInControl({auth,restart,nativeAvailable:true});control.authenticated();
 const settings=document.createElement('div');document.body.append(settings);control.mountSettings(settings);
 document.querySelector("button")!.click();expect(restart).not.toHaveBeenCalled();
 reject(new Error("synthetic failure"));await vi.waitFor(()=>expect(document.body.textContent).toContain("Sign-out did not complete"));
 expect(restart).not.toHaveBeenCalled();expect(auth.signOut).toHaveBeenCalledTimes(1);
 document.querySelector("button")!.click();resolve();await vi.waitFor(()=>expect(restart).toHaveBeenCalledOnce());control.dispose();
});
