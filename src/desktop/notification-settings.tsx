import { useEffect, useState } from "react";
import { notificationRequest } from "./notifications";
export function AndroidNotificationSettings() {
  const [permission, setPermission] = useState("unavailable");
  const refresh = () => {
    const result = notificationRequest("status");
    setPermission(typeof result.permission === "string" ? result.permission : "unavailable");
  };
  useEffect(() => {
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("hermes:notification-tap", refresh);
    return () => { window.removeEventListener("focus", refresh); window.removeEventListener("hermes:notification-tap", refresh); };
  }, []);
  return <section className="space-y-2">
    <h3 className="font-medium">Android notifications</h3>
    <p role="status" className="text-sm">Android notification permission: {permission}</p>
    {permission === "not-requested" && <button type="button" onClick={() => {
      const result = notificationRequest("request");
      setPermission(typeof result.permission === "string" ? result.permission : "unavailable");
    }}>Allow Android notifications</button>}
    <button type="button" onClick={refresh}>Refresh notification permission</button>
    <p className="text-sm text-muted-foreground">Desktop notification preferences still apply. If denied or blocked, enable notifications in Android App info → Notifications. Notification buttons open Hermes for review; they never approve a request. Delivery requires the running client connection; force-stop or process-death push delivery is not supported.</p>
  </section>;
}
