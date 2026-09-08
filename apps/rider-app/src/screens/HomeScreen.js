import React, { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView, ActivityIndicator } from "react-native";
import { theme } from "../theme";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

const VEHICLES = ["bike", "auto", "sedan", "suv"];

export default function HomeScreen({ navigation }) {
  const { user, logout } = useAuth();
  const [pickup, setPickup] = useState({ lng: "77.5946", lat: "12.9716", address: "MG Road" });
  const [drop, setDrop] = useState({ lng: "77.6446", lat: "12.9352", address: "Koramangala" });
  const [vehicle, setVehicle] = useState("sedan");
  const [payment, setPayment] = useState("wallet");
  const [estimate, setEstimate] = useState(null);
  const [wallet, setWallet] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const loadWallet = async () => { try { setWallet(await api.wallet()); } catch {} };
  useEffect(() => { loadWallet(); }, []);

  const doEstimate = async () => {
    setErr("");
    try {
      const e = await api.estimate({ city: "Bangalore", vehicle_type: vehicle, distance_km: 5, duration_min: 15 });
      setEstimate(e);
    } catch (e) { setErr(e.message); }
  };

  const book = async () => {
    setErr(""); setLoading(true);
    try {
      const ride = await api.createRide({
        pickup: { lng: parseFloat(pickup.lng), lat: parseFloat(pickup.lat), address: pickup.address },
        drop: { lng: parseFloat(drop.lng), lat: parseFloat(drop.lat), address: drop.address },
        vehicle_type: vehicle, city: "Bangalore", payment_method: payment,
      });
      navigation.navigate("Ride", { rideId: ride.id });
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <ScrollView style={s.container} contentContainerStyle={{ padding: 20, paddingTop: 60 }}>
      <View style={s.topRow}>
        <View>
          <Text style={s.hi}>Hi{user?.name ? `, ${user.name}` : ""} 👋</Text>
          <Text style={s.muted}>Where to?</Text>
        </View>
        <TouchableOpacity style={s.walletChip} onPress={loadWallet}>
          <Text style={s.walletLabel}>Wallet</Text>
          <Text style={s.walletVal}>₹{wallet ? wallet.balance.toFixed(2) : "—"}</Text>
        </TouchableOpacity>
      </View>

      <View style={s.card}>
        <Text style={s.section}>Pickup</Text>
        <TextInput style={s.input} value={pickup.address} onChangeText={(t) => setPickup({ ...pickup, address: t })} placeholder="Pickup address" placeholderTextColor={theme.muted} />
        <View style={s.row}>
          <TextInput style={[s.input, s.half]} value={pickup.lng} onChangeText={(t) => setPickup({ ...pickup, lng: t })} keyboardType="numbers-and-punctuation" placeholder="lng" placeholderTextColor={theme.muted} />
          <TextInput style={[s.input, s.half]} value={pickup.lat} onChangeText={(t) => setPickup({ ...pickup, lat: t })} keyboardType="numbers-and-punctuation" placeholder="lat" placeholderTextColor={theme.muted} />
        </View>
        <Text style={s.section}>Drop</Text>
        <TextInput style={s.input} value={drop.address} onChangeText={(t) => setDrop({ ...drop, address: t })} placeholder="Drop address" placeholderTextColor={theme.muted} />
        <View style={s.row}>
          <TextInput style={[s.input, s.half]} value={drop.lng} onChangeText={(t) => setDrop({ ...drop, lng: t })} keyboardType="numbers-and-punctuation" placeholder="lng" placeholderTextColor={theme.muted} />
          <TextInput style={[s.input, s.half]} value={drop.lat} onChangeText={(t) => setDrop({ ...drop, lat: t })} keyboardType="numbers-and-punctuation" placeholder="lat" placeholderTextColor={theme.muted} />
        </View>
      </View>

      <Text style={s.section}>Ride type</Text>
      <View style={s.chips}>
        {VEHICLES.map((v) => (
          <TouchableOpacity key={v} style={[s.chip, vehicle === v && s.chipOn]} onPress={() => setVehicle(v)} testID={`vehicle-${v}`}>
            <Text style={[s.chipText, vehicle === v && s.chipTextOn]}>{v.toUpperCase()}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={s.section}>Pay with</Text>
      <View style={s.chips}>
        {["wallet", "cash"].map((p) => (
          <TouchableOpacity key={p} style={[s.chip, payment === p && s.chipOn]} onPress={() => setPayment(p)} testID={`pay-${p}`}>
            <Text style={[s.chipText, payment === p && s.chipTextOn]}>{p.toUpperCase()}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <TouchableOpacity style={s.ghostBtn} onPress={doEstimate}><Text style={s.ghostText}>Estimate fare</Text></TouchableOpacity>
      {estimate && (
        <View style={s.estimate}>
          <Text style={s.estTotal}>≈ ₹{estimate.total}</Text>
          <Text style={s.muted}>base ₹{estimate.base_fare} · dist ₹{estimate.distance_fare} · time ₹{estimate.time_fare} · tax ₹{estimate.tax}</Text>
        </View>
      )}

      {!!err && <Text style={s.err}>{err}</Text>}
      <TouchableOpacity style={s.btn} onPress={book} disabled={loading} testID="book-ride-btn">
        {loading ? <ActivityIndicator color="#04120E" /> : <Text style={s.btnText}>Book ride</Text>}
      </TouchableOpacity>

      <TouchableOpacity style={{ marginTop: 24 }} onPress={() => api.topup(500).then(loadWallet)}>
        <Text style={s.link}>+ Add ₹500 to wallet</Text>
      </TouchableOpacity>
      <TouchableOpacity style={{ marginTop: 12 }} onPress={logout}><Text style={s.logout}>Sign out</Text></TouchableOpacity>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.bg },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 20 },
  hi: { color: theme.text, fontSize: 26, fontWeight: "800" },
  muted: { color: theme.muted, marginTop: 2 },
  walletChip: { backgroundColor: theme.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: theme.border, alignItems: "flex-end" },
  walletLabel: { color: theme.muted, fontSize: 11 },
  walletVal: { color: theme.accent, fontWeight: "800", fontSize: 16 },
  card: { backgroundColor: theme.surface, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.border },
  section: { color: theme.muted, fontSize: 13, marginTop: 16, marginBottom: 8, fontWeight: "700", letterSpacing: 1 },
  input: { backgroundColor: theme.surfaceAlt, borderRadius: 12, padding: 14, color: theme.text, borderWidth: 1, borderColor: theme.border, marginBottom: 10 },
  row: { flexDirection: "row", gap: 10 },
  half: { flex: 1 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  chip: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: 999, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surface },
  chipOn: { backgroundColor: theme.accent, borderColor: theme.accent },
  chipText: { color: theme.muted, fontWeight: "700" },
  chipTextOn: { color: "#04120E" },
  ghostBtn: { marginTop: 18, borderWidth: 1, borderColor: theme.accent, borderRadius: 12, padding: 14, alignItems: "center" },
  ghostText: { color: theme.accent, fontWeight: "700" },
  estimate: { marginTop: 12, backgroundColor: theme.surfaceAlt, borderRadius: 12, padding: 14, borderWidth: 1, borderColor: theme.border },
  estTotal: { color: theme.text, fontSize: 24, fontWeight: "800" },
  btn: { backgroundColor: theme.accent, borderRadius: 14, padding: 18, alignItems: "center", marginTop: 18 },
  btnText: { color: "#04120E", fontWeight: "800", fontSize: 17 },
  link: { color: theme.accent, textAlign: "center", fontWeight: "700" },
  logout: { color: theme.muted, textAlign: "center" },
  err: { color: theme.danger, marginTop: 12, textAlign: "center" },
});
