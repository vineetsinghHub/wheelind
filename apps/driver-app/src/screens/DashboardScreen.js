import React, { useEffect, useRef, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView, ActivityIndicator, Alert } from "react-native";
import { theme } from "../theme";
import { api, openSocket, sendLocation } from "../api";
import { useAuth } from "../context/AuthContext";

// Demo shift location (Bangalore). Replace with device GPS + real map later.
const LOC = { lng: 77.5946, lat: 12.9716 };

export default function DashboardScreen() {
  const { user, logout } = useAuth();
  const [profile, setProfile] = useState(null);
  const [presence, setPresence] = useState(null);
  const [vehicles, setVehicles] = useState([]);
  const [online, setOnline] = useState(false);
  const [offers, setOffers] = useState([]);
  const [activeRide, setActiveRide] = useState(null);
  const [otp, setOtp] = useState("");
  const [earnings, setEarnings] = useState(null);
  const [busy, setBusy] = useState(false);
  const wsRef = useRef(null);
  const hbRef = useRef(null);
  const activeRef = useRef(null);
  useEffect(() => { activeRef.current = activeRide ? activeRide.id : null; }, [activeRide]);

  const load = async () => {
    try {
      const me = await api.me();
      setProfile(me.profile); setPresence(me.presence);
      setOnline(me.presence && me.presence.status !== "offline");
      setVehicles(await api.myVehicles());
      setEarnings(await api.earnings());
    } catch (e) {}
  };
  useEffect(() => { load(); return () => cleanup(); }, []);

  const cleanup = () => {
    if (wsRef.current) try { wsRef.current.close(); } catch {}
    if (hbRef.current) clearInterval(hbRef.current);
  };

  const connectRealtime = () => {
    const ws = openSocket(async (msg) => {
      if (msg.type === "offer") setOffers((prev) => [msg.offer, ...prev.filter((x) => x.id !== msg.offer.id)]);
      if (msg.type === "ride_update" && activeRef.current) {
        try { setActiveRide(await api.getRide(activeRef.current)); } catch {}
      }
    });
    wsRef.current = ws;
    hbRef.current = setInterval(() => {
      sendLocation(ws, LOC.lng, LOC.lat);
      api.heartbeat({ lng: LOC.lng, lat: LOC.lat }).catch(() => {});
    }, 8000);
  };

  const doOnline = async () => {
    if (!profile) return;
    if (profile.kyc_status !== "approved") return Alert.alert("KYC pending", "Await admin approval before going online.");
    const active = vehicles.find((v) => v.is_active && v.status === "approved");
    if (!active) return Alert.alert("No active vehicle", "Add & activate an approved vehicle first.");
    setBusy(true);
    try {
      await api.goOnline({ lng: LOC.lng, lat: LOC.lat, vehicle_type: active.vehicle_type });
      setOnline(true);
      connectRealtime();
      setOffers(await api.offers());
    } catch (e) { Alert.alert("Error", e.message); }
    setBusy(false);
  };

  const doOffline = async () => {
    setBusy(true);
    try { await api.offline(); } catch {}
    setOnline(false); cleanup(); setOffers([]);
    setBusy(false);
  };

  const accept = async (offerId) => {
    try { const ride = await api.accept(offerId); setActiveRide(ride); setOffers([]); }
    catch (e) { Alert.alert("Error", e.message); setOffers(await api.offers()); }
  };
  const reject = async (offerId) => {
    await api.reject(offerId).catch(() => {});
    setOffers((prev) => prev.filter((o) => o.id !== offerId));
  };

  const arrived = async () => { const r = await api.arrived(activeRide.id).then(() => api.getRide(activeRide.id)); setActiveRide(r); };
  const start = async () => {
    try { await api.start(activeRide.id, otp); setActiveRide(await api.getRide(activeRide.id)); setOtp(""); }
    catch (e) { Alert.alert("Invalid OTP", e.message); }
  };
  const complete = async () => {
    const res = await api.complete(activeRide.id);
    Alert.alert("Trip complete", `You earned ₹${res.earning.net_earning}`);
    setActiveRide(null); setEarnings(await api.earnings());
    if (online) setOffers(await api.offers());
  };

  const submitKyc = async () => { await api.submitDoc("driving_license", "DL-DEMO-123"); Alert.alert("Submitted", "KYC document sent for admin review."); load(); };
  const addVehicle = async () => {
    const plate = "KA01" + Math.random().toString(36).slice(2, 6).toUpperCase();
    await api.addVehicle({ vehicle_type: "sedan", make: "Honda", model: "City", plate_number: plate });
    Alert.alert("Vehicle added", "Await admin approval, then activate."); setVehicles(await api.myVehicles());
  };
  const activate = async (id) => { try { await api.activateVehicle(id); setVehicles(await api.myVehicles()); } catch (e) { Alert.alert("Error", e.message); } };
  const subscribe = async () => { await api.subscribe(); Alert.alert("Subscribed", "Zero-commission active for 30 days."); };

  if (!profile) return <View style={s.center}><ActivityIndicator color={theme.accent} /></View>;

  const kycApproved = profile.kyc_status === "approved";

  return (
    <ScrollView style={s.container} contentContainerStyle={{ padding: 20, paddingTop: 60 }}>
      <View style={s.header}>
        <View>
          <Text style={s.name}>{profile.name || "Driver"}</Text>
          <Text style={s.muted}>★ {profile.rating} · {profile.total_trips} trips</Text>
        </View>
        <View style={[s.statusDot, { backgroundColor: online ? theme.accent : theme.muted }]} />
      </View>

      {/* Online toggle */}
      <TouchableOpacity style={[s.bigToggle, online ? s.onlineBg : s.offlineBg]} onPress={online ? doOffline : doOnline} disabled={busy} testID="online-toggle">
        {busy ? <ActivityIndicator color="#04120E" /> : <Text style={[s.toggleText, online && { color: "#04120E" }]}>{online ? "YOU'RE ONLINE — tap to go offline" : "GO ONLINE"}</Text>}
      </TouchableOpacity>

      {/* Onboarding */}
      {!kycApproved && (
        <View style={s.card}>
          <Text style={s.section}>Get road-ready</Text>
          <Text style={s.muted}>KYC status: {profile.kyc_status}</Text>
          <TouchableOpacity style={s.ghost} onPress={submitKyc}><Text style={s.ghostText}>Submit KYC (driving license)</Text></TouchableOpacity>
          <TouchableOpacity style={s.ghost} onPress={addVehicle}><Text style={s.ghostText}>Add vehicle</Text></TouchableOpacity>
          <Text style={[s.muted, { marginTop: 8 }]}>An admin approves KYC & vehicle before you can go online.</Text>
        </View>
      )}

      {/* Vehicles */}
      {vehicles.length > 0 && (
        <View style={s.card}>
          <Text style={s.section}>Vehicles</Text>
          {vehicles.map((v) => (
            <View key={v.id} style={s.vehRow}>
              <Text style={s.vehText}>{v.vehicle_type.toUpperCase()} · {v.plate_number}</Text>
              <View style={s.vehRight}>
                <Text style={[s.tag, v.status === "approved" ? s.tagOk : s.tagWait]}>{v.status}</Text>
                {v.status === "approved" && !v.is_active && (
                  <TouchableOpacity onPress={() => activate(v.id)}><Text style={s.activate}>Activate</Text></TouchableOpacity>
                )}
                {v.is_active && <Text style={s.activeTag}>ACTIVE</Text>}
              </View>
            </View>
          ))}
        </View>
      )}

      {/* Incoming offers */}
      {online && !activeRide && (
        <View style={s.card}>
          <Text style={s.section}>Ride requests</Text>
          {offers.length === 0 ? (
            <Text style={s.muted}>Waiting for requests…</Text>
          ) : offers.map((o) => (
            <View key={o.id} style={s.offer}>
              <Text style={s.offerFare}>₹{o.fare_estimate}</Text>
              <Text style={s.muted}>{o.vehicle_type.toUpperCase()} · {o.pickup?.address || "pickup"}{o.distance_m ? ` · ${Math.round(o.distance_m)}m away` : ""}</Text>
              <View style={s.offerBtns}>
                <TouchableOpacity style={s.accept} onPress={() => accept(o.id)} testID="accept-offer-btn"><Text style={s.acceptText}>Accept</Text></TouchableOpacity>
                <TouchableOpacity style={s.rejectBtn} onPress={() => reject(o.id)}><Text style={s.rejectText}>Skip</Text></TouchableOpacity>
              </View>
            </View>
          ))}
        </View>
      )}

      {/* Active trip */}
      {activeRide && (
        <View style={s.card}>
          <Text style={s.section}>Active trip · {activeRide.status.replace("_", " ")}</Text>
          <Text style={s.muted}>Pickup: {activeRide.pickup?.address}</Text>
          <Text style={s.muted}>Drop: {activeRide.drop?.address}</Text>
          <Text style={[s.offerFare, { marginTop: 8 }]}>₹{(activeRide.fare_final || activeRide.fare_estimate).total}</Text>

          {activeRide.status === "driver_assigned" && (
            <TouchableOpacity style={s.primary} onPress={arrived}><Text style={s.primaryText}>I've arrived</Text></TouchableOpacity>
          )}
          {activeRide.status === "arrived" && (
            <>
              <TextInput style={s.otpInput} value={otp} onChangeText={setOtp} keyboardType="number-pad" maxLength={4} placeholder="Enter rider OTP" placeholderTextColor={theme.muted} />
              <TouchableOpacity style={s.primary} onPress={start} testID="start-trip-btn"><Text style={s.primaryText}>Start trip</Text></TouchableOpacity>
            </>
          )}
          {activeRide.status === "in_progress" && (
            <TouchableOpacity style={s.primary} onPress={complete} testID="complete-trip-btn"><Text style={s.primaryText}>Complete trip</Text></TouchableOpacity>
          )}
        </View>
      )}

      {/* Earnings */}
      {earnings && (
        <View style={s.card}>
          <Text style={s.section}>Earnings</Text>
          <Text style={s.earnBig}>₹{earnings.summary.net.toFixed(2)}</Text>
          <Text style={s.muted}>{earnings.summary.trips} trips · commission ₹{earnings.summary.commission.toFixed(2)} · pending payout ₹{earnings.summary.pending_payout.toFixed(2)}</Text>
          <TouchableOpacity style={s.ghost} onPress={subscribe}><Text style={s.ghostText}>Go zero-commission (subscription)</Text></TouchableOpacity>
        </View>
      )}

      <TouchableOpacity style={{ marginTop: 12, marginBottom: 40 }} onPress={logout}><Text style={s.logout}>Sign out</Text></TouchableOpacity>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.bg },
  center: { flex: 1, backgroundColor: theme.bg, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 18 },
  name: { color: theme.text, fontSize: 26, fontWeight: "800" },
  muted: { color: theme.muted, marginTop: 4 },
  statusDot: { width: 16, height: 16, borderRadius: 999 },
  bigToggle: { borderRadius: theme.radius, padding: 22, alignItems: "center", marginBottom: 18 },
  offlineBg: { backgroundColor: theme.surface, borderWidth: 1, borderColor: theme.accent },
  onlineBg: { backgroundColor: theme.accent },
  toggleText: { color: theme.accent, fontWeight: "800", fontSize: 16 },
  card: { backgroundColor: theme.surface, borderRadius: theme.radius, padding: 18, borderWidth: 1, borderColor: theme.border, marginBottom: 16 },
  section: { color: theme.muted, fontSize: 13, marginBottom: 10, fontWeight: "700", letterSpacing: 1 },
  ghost: { borderWidth: 1, borderColor: theme.accent, borderRadius: 10, padding: 13, alignItems: "center", marginTop: 10 },
  ghostText: { color: theme.accent, fontWeight: "700" },
  vehRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8 },
  vehText: { color: theme.text, fontWeight: "600" },
  vehRight: { flexDirection: "row", alignItems: "center", gap: 10 },
  tag: { fontSize: 11, fontWeight: "800", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, overflow: "hidden" },
  tagOk: { color: "#04120E", backgroundColor: theme.accent },
  tagWait: { color: theme.amber, borderWidth: 1, borderColor: theme.amber },
  activate: { color: theme.accent, fontWeight: "700" },
  activeTag: { color: theme.accent, fontWeight: "800", fontSize: 11 },
  offer: { backgroundColor: theme.surfaceAlt, borderRadius: 12, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: theme.border },
  offerFare: { color: theme.text, fontSize: 24, fontWeight: "800" },
  offerBtns: { flexDirection: "row", gap: 10, marginTop: 12 },
  accept: { flex: 1, backgroundColor: theme.accent, borderRadius: 10, padding: 13, alignItems: "center" },
  acceptText: { color: "#04120E", fontWeight: "800" },
  rejectBtn: { paddingHorizontal: 18, borderRadius: 10, padding: 13, alignItems: "center", borderWidth: 1, borderColor: theme.border },
  rejectText: { color: theme.muted, fontWeight: "700" },
  primary: { backgroundColor: theme.accent, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 14 },
  primaryText: { color: "#04120E", fontWeight: "800", fontSize: 16 },
  otpInput: { backgroundColor: theme.surfaceAlt, borderRadius: 12, padding: 14, color: theme.text, fontSize: 22, letterSpacing: 8, textAlign: "center", borderWidth: 1, borderColor: theme.border, marginTop: 14 },
  earnBig: { color: theme.accent, fontSize: 30, fontWeight: "900" },
  logout: { color: theme.muted, textAlign: "center" },
});
