"use client";

import { useEffect, useState } from "react";
import { UNAUTHORIZED_EVENT } from "../lib/api";

/**
 * True once the server has rejected our credentials (HTTP 401 or WebSocket
 * close 4401). It never resets: saving a key in the AuthBanner reloads the
 * page, which starts over with a fresh state.
 */
export function useUnauthorized(): boolean {
  const [unauthorized, setUnauthorized] = useState(false);

  useEffect(() => {
    const onUnauthorized = () => setUnauthorized(true);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  return unauthorized;
}
