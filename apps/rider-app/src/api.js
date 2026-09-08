import AsyncStorage from "@react-native-async-storage/async-storage";
import { API_URL, WS_URL } from "./config";

let TOKEN = null;

export async function loadToken() {
  TOKEN = await AsyncStorage.getItem("wheelind_rider_token");
  return TOKEN;
}
export async function setToken(t) {
  TOKEN = t;
  if (t) await AsyncStorage.setItem("wheelind_rider_token", t);
  else await AsyncStorage.removeItem("wheelind_rider_token");
}
export function getToken() {
  return TOKEN;
}

async function req(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : `Error ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  requestOtp: (phone) => req("/api/auth/otp/request", { method: "POST", auth: false, body: { phone, role: "rider" } }),
  verifyOtp: (phone, code, name) => req("/api/auth/otp/verify", { method: "POST", auth: false, body: { phone, code, role: "rider", name } }),
  me: () => req("/api/auth/me"),
  wallet: () => req("/api/wallet"),
  topup: (amount) => req("/api/wallet/topup", { method: "POST", body: { amount } }),
  estimate: (b) => req("/api/fare/estimate", { method: "POST", body: b }),
  createRide: (b) => req("/api/rides", { method: "POST", body: b }),
  getRide: (id) => req(`/api/rides/${id}`),
  myRides: () => req("/api/rides"),
  increaseFare: (id, amount) => req(`/api/rides/${id}/increase-fare`, { method: "POST", body: { amount } }),
  cancelRide: (id) => req(`/api/rides/${id}/cancel`, { method: "POST" }),
};

export function openSocket(onMessage) {
  const ws = new WebSocket(`${WS_URL}?token=${TOKEN}`);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch {}
  };
  return ws;
}
