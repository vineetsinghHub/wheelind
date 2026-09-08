import React, { createContext, useContext, useEffect, useState } from "react";
import { api, loadToken, setToken, getToken } from "../api";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading

  useEffect(() => {
    (async () => {
      await loadToken();
      if (getToken()) {
        try {
          const me = await api.me();
          setUser(me.user);
        } catch {
          await setToken(null);
          setUser(null);
        }
      } else setUser(null);
    })();
  }, []);

  const login = async (phone, code, name) => {
    const res = await api.verifyOtp(phone, code, name);
    await setToken(res.access_token);
    setUser(res.user);
    return res;
  };
  const logout = async () => {
    await setToken(null);
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}
