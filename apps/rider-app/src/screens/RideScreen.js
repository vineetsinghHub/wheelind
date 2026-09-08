import React, { useEffect, useRef, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, ActivityIndicator } from "react-native";
import { theme } from "../theme";
import { api, openSocket } from "../api";

const STATUS_LABEL = {
  searching: "Finding your driver…",
  driver_assigned: "Driver assigned — on the way",
  arrived: "Your driver has arrived",
  in_progress: "On trip",
  completed: "Trip completed",
  cancelled: "Ride cancelled",
  no_drivers: "No drivers available",
};

export default function RideScreen({ route, navigation }) {
  const { rideId } = route.params;
  const [ride, setRide] = useState(null);
  const [driverLoc, setDriverLoc] = useState(null);
  const [err, setErr] = useState("");
  const wsRef = useRef(null);

  const refresh = async () => { try { setRide(await api.getRide(rideId)); } catch (e) { setErr(e.message); } };

  useEffect(() => {
    refresh();
    const ws = openSocket((msg) => {
      if (msg.type === "ride_update" && msg.ride_id === rideId) refresh();
      if (msg.type === "driver_location" && msg.ride_id === rideId) setDriverLoc({ lng: msg.lng, lat: msg.lat });
    });
    wsRef.current = ws;
    const poll = setInterval(refresh, 5000);
    return () => { try { ws.close(); } catch {} clearInterval(poll); };
  }, [rideId]);

  if (!ride) return <View style={s.center}><ActivityIndicator color={theme.accent} /></View>;

  const status = ride.status;
  const active = ["searching", "driver_assigned", "arrived", "in_progress"].includes(status);

  return (
    <ScrollView style={s.container} contentContainerStyle={{ padding: 20, paddingTop: 60 }}>
      <View style={s.statusCard}>
        {status === "searching" && <ActivityIndicator color={theme.accent} style={{ marginBottom: 12 }} />}
        <Text style={s.statusText}>{STATUS_LABEL[status] || status}</Text>
        {status === "searching" && <Text style={s.muted}>Attempt {ride.dispatch_attempt}</Text>}
      </View>

      {["driver_assigned", "arrived", "in_progress"].includes(status) && (
        <View style={s.card}>
          <Text style={s.section}>Your trip OTP</Text>
          <Text style={s.otp}>{ride.trip_otp}</Text>
          <Text style={s.muted}>Share with driver to start the trip</Text>
          {driverLoc && <Text style={[s.muted, { marginTop: 12 }]}>Driver live: {driverLoc.lat.toFixed(4)}, {driverLoc.lng.toFixed(4)}</Text>}
        </View>
      )}

      <View style={s.card}>
        <Text style={s.section}>Fare</Text>
        <Text style={s.fare}>₹{(ride.fare_final || ride.fare_estimate).total}</Text>
        {ride.rider_added > 0 && <Text style={s.muted}>Includes +₹{ride.rider_added} you added</Text>}
        <Text style={s.muted}>{ride.vehicle_type.toUpperCase()} · {ride.payment_method.toUpperCase()} · {ride.route.distance_km} km</Text>
      </View>

      {!!err && <Text style={s.err}>{err}</Text>}

      {status === "searching" && (
        <TouchableOpacity style={s.ghostBtn} onPress={() => api.increaseFare(rideId, 20).then(refresh)} testID="increase-fare-btn">
          <Text style={s.ghostText}>Boost fare +₹20 to find a driver faster</Text>
        </TouchableOpacity>
      )}
      {status === "no_drivers" && (
        <TouchableOpacity style={s.ghostBtn} onPress={() => api.increaseFare(rideId, 30).then(refresh)}>
          <Text style={s.ghostText}>Retry with +₹30</Text>
        </TouchableOpacity>
      )}

      {active && (
        <TouchableOpacity style={s.cancelBtn} onPress={() => api.cancelRide(rideId).then(refresh)} testID="cancel-ride-btn">
          <Text style={s.cancelText}>Cancel ride</Text>
        </TouchableOpacity>
      )}
      {!active && (
        <TouchableOpacity style={s.btn} onPress={() => navigation.replace("Home")}>
          <Text style={s.btnText}>Back to home</Text>
        </TouchableOpacity>
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.bg },
  center: { flex: 1, backgroundColor: theme.bg, alignItems: "center", justifyContent: "center" },
  statusCard: { backgroundColor: theme.surface, borderRadius: theme.radius, padding: 24, borderWidth: 1, borderColor: theme.border, alignItems: "center", marginBottom: 16 },
  statusText: { color: theme.text, fontSize: 22, fontWeight: "800", textAlign: "center" },
  card: { backgroundColor: theme.surface, borderRadius: theme.radius, padding: 20, borderWidth: 1, borderColor: theme.border, marginBottom: 16 },
  section: { color: theme.muted, fontSize: 13, marginBottom: 8, fontWeight: "700", letterSpacing: 1 },
  otp: { color: theme.accent, fontSize: 44, fontWeight: "900", letterSpacing: 10 },
  fare: { color: theme.text, fontSize: 30, fontWeight: "800" },
  muted: { color: theme.muted, marginTop: 4 },
  ghostBtn: { borderWidth: 1, borderColor: theme.accent, borderRadius: 12, padding: 16, alignItems: "center", marginBottom: 12 },
  ghostText: { color: theme.accent, fontWeight: "700" },
  cancelBtn: { borderWidth: 1, borderColor: theme.danger, borderRadius: 12, padding: 16, alignItems: "center" },
  cancelText: { color: theme.danger, fontWeight: "700" },
  btn: { backgroundColor: theme.accent, borderRadius: 14, padding: 18, alignItems: "center" },
  btnText: { color: "#04120E", fontWeight: "800", fontSize: 16 },
  err: { color: theme.danger, marginBottom: 12, textAlign: "center" },
});
