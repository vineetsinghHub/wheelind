import AsyncStorage from "@react-native-async-storage/async-storage";
import { API_URL, WS_URL } from "./config";

let TOKEN = null;
export async function loadToken() { TOKEN = await AsyncStorage.getItem("wheelind_driver_token"); return TOKEN; }
export async function setToken(t) { TOKEN = t; if (t) await AsyncStorage.setItem("wheelind_driver_token", t); else await AsyncStorage.removeItem("wheelind_driver_token"); }
export function getToken() { return TOKEN; }

async function req(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  const res = await fetch(`${API_URL}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : `Error ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  requestOtp: (phone) => req("/api/auth/otp/request", { method: "POST", auth: false, body: { phone, role: "driver" } }),
  verifyOtp: (phone, code, name) => req("/api/auth/otp/verify", { method: "POST", auth: false, body: { phone, code, role: "driver", name } }),
  me: () => req("/api/drivers/me"),
  submitDoc: (doc_type, number) => req("/api/documents", { method: "POST", body: { doc_type, file_key: `kyc/${doc_type}.jpg`, number } }),
  myDocs: () => req("/api/documents"),
  addVehicle: (b) => req("/api/vehicles", { method: "POST", body: b }),
  myVehicles: () => req("/api/vehicles"),
  activateVehicle: (id) => req(`/api/vehicles/${id}/activate`, { method: "POST" }),
  goOnline: (b) => req("/api/presence/online", { method: "POST", body: b }),
  heartbeat: (b) => req("/api/presence/heartbeat", { method: "POST", body: b }),
  offline: () => req("/api/presence/offline", { method: "POST" }),
  offers: () => req("/api/driver/offers"),
  accept: (id) => req(`/api/offers/${id}/accept`, { method: "POST" }),
  reject: (id) => req(`/api/offers/${id}/reject`, { method: "POST" }),
  getRide: (id) => req(`/api/rides/${id}`),
  arrived: (id) => req(`/api/rides/${id}/arrived`, { method: "POST" }),
  start: (id, otp) => req(`/api/rides/${id}/start`, { method: "POST", body: { otp } }),
  complete: (id, b) => req(`/api/rides/${id}/complete`, { method: "POST", body: b || {} }),
  earnings: () => req("/api/driver/earnings"),
  subscribe: () => req("/api/driver/subscriptions", { method: "POST", body: { plan: "zero_commission", days: 30 } }),
};

export function openSocket(onMessage) {
  const ws = new WebSocket(`${WS_URL}?token=${TOKEN}`);
  ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch {} };
  return ws;
}

export function sendLocation(ws, lng, lat) {
  try { ws.send(JSON.stringify({ type: "location", lng, lat })); } catch {}
}
