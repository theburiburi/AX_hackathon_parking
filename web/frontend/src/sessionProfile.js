// Re-read display fields from the server; the token remains the login credential.
export function watchSessionProfile({ load, onUser, onExpired, windowTarget = window, documentTarget = document }) {
  const controller = new AbortController();
  let stopped = false, pending = false;
  const refresh = async () => {
    if (stopped || pending) return;
    pending = true;
    try {
      const user = await load(controller.signal);
      if (!stopped) onUser(user);
    } catch (error) {
      // Temporary connection failures must not erase an otherwise valid login.
      if (!stopped && error.status === 401) onExpired();
    } finally {
      pending = false;
    }
  };
  const refreshVisible = () => {
    if (documentTarget.visibilityState !== "hidden") refresh();
  };
  refresh();
  const timer = setInterval(refreshVisible, 30000);
  windowTarget.addEventListener("focus", refreshVisible);
  documentTarget.addEventListener("visibilitychange", refreshVisible);
  return () => {
    stopped = true;
    controller.abort();
    clearInterval(timer);
    windowTarget.removeEventListener("focus", refreshVisible);
    documentTarget.removeEventListener("visibilitychange", refreshVisible);
  };
}
