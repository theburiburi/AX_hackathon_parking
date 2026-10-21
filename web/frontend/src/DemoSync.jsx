import React, { useEffect, useState } from "react";
import { watchDemoState } from "./demoStatePolling";

export function useDemoState(api, token, enabled = true) {
  const [state, setState] = useState({ playback: null, vehicles: [], zones: null, error: "" });
  useEffect(() => {
    if (!enabled) return;
    return watchDemoState({
      load: async signal => {
        const response = await fetch(`${api}/replay/demo-state/`, {
          headers: { Authorization: `Bearer ${token}` }, signal, cache: "no-store",
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "데모 동기화에 실패했습니다.");
        return data;
      },
      onState: data => setState({ ...data, error: "" }),
      onError: error => setState(previous => previous.error === (error?.message || "")
        ? previous : { ...previous, error: error?.message || "" }),
    });
  }, [api, token, enabled]);
  return state;
}
