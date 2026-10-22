import { useLayoutEffect, useRef } from "react";
import { registry } from "../../vendor/hermes/apps/desktop/src/contrib/registry";
import { settingsPageContribution } from "../../vendor/hermes/apps/desktop/src/contrib/settings-pages";
import type { installSignInControl } from "./auth-control";
import { AndroidNotificationSettings } from "./notification-settings";

type AccountControl = Pick<ReturnType<typeof installSignInControl>, "mountSettings">;

function PcAccountSettings({ control }: { control: AccountControl }) {
  const account = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (account.current) return control.mountSettings(account.current);
  }, [control]);
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-medium">PC connection</h2>
      <p className="text-sm text-muted-foreground">
        Sign-in is encrypted on this Android device. Signing out removes this
        device&apos;s saved login; it does not sign out your system browser or PC.
      </p>
      <div ref={account} />
      <AndroidNotificationSettings />
    </section>
  );
}

/** A client-only Settings contribution; no plugin installation or PC settings write. */
export function installPcAccountSettings(control: AccountControl): () => void {
  // This contribution is installed only after primary bootstrap. Keep store
  // imports out of the cold host module and capture routing before each show.
  if (window.HermesPc) void import("./notification-runtime").then(module => module.initializeNotificationRouting()).catch(() => {});
  return registry.register({
    ...settingsPageContribution({
      id: "android.pc-connection",
      title: "PC connection",
      icon: "plug",
      order: -100,
      render: () => <PcAccountSettings control={control} />,
    }),
    source: "core",
  });
}
