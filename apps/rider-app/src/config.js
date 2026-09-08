// Wheelind Rider — backend connection config.
// Point this at your running Wheelind API. Default = Emergent preview backend.
export const API_URL = "https://backend-first-7.preview.emergentagent.com";
export const WS_URL = API_URL.replace(/^http/, "ws") + "/api/ws";
