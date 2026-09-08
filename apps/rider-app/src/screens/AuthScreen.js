import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { theme } from "../theme";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export default function AuthScreen() {
  const { login } = useAuth();
  const [phone, setPhone] = useState("+919000000001");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState("phone");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const sendOtp = async () => {
    setErr(""); setLoading(true);
    try {
      const r = await api.requestOtp(phone);
      if (r.debug_code) setCode(r.debug_code); // dev convenience
      setStage("otp");
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };
  const verify = async () => {
    setErr(""); setLoading(true);
    try { await login(phone, code, name); } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.container}>
      <View style={s.badge}><Text style={s.badgeText}>WHEELIND</Text></View>
      <Text style={s.title}>Move with the{"\n"}city's rhythm.</Text>
      <Text style={s.sub}>Rider sign in</Text>

      <View style={s.card}>
        {stage === "phone" ? (
          <>
            <Text style={s.label}>Phone number</Text>
            <TextInput style={s.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="+9190000..." placeholderTextColor={theme.muted} />
            <Text style={s.label}>Name (optional)</Text>
            <TextInput style={s.input} value={name} onChangeText={setName} placeholder="Your name" placeholderTextColor={theme.muted} />
            <TouchableOpacity style={s.btn} onPress={sendOtp} disabled={loading} testID="rider-send-otp-btn">
              {loading ? <ActivityIndicator color="#04120E" /> : <Text style={s.btnText}>Send OTP</Text>}
            </TouchableOpacity>
          </>
        ) : (
          <>
            <Text style={s.label}>Enter OTP sent to {phone}</Text>
            <TextInput style={[s.input, s.otp]} value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={6} placeholder="••••••" placeholderTextColor={theme.muted} />
            <TouchableOpacity style={s.btn} onPress={verify} disabled={loading} testID="rider-verify-otp-btn">
              {loading ? <ActivityIndicator color="#04120E" /> : <Text style={s.btnText}>Verify & Continue</Text>}
            </TouchableOpacity>
            <TouchableOpacity onPress={() => setStage("phone")}><Text style={s.link}>Change number</Text></TouchableOpacity>
          </>
        )}
        {!!err && <Text style={s.err}>{err}</Text>}
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.bg, padding: 24, justifyContent: "center" },
  badge: { alignSelf: "flex-start", borderWidth: 1, borderColor: theme.accent, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5, marginBottom: 24 },
  badgeText: { color: theme.accent, fontWeight: "800", letterSpacing: 3, fontSize: 12 },
  title: { color: theme.text, fontSize: 38, fontWeight: "800", lineHeight: 42 },
  sub: { color: theme.muted, marginTop: 10, marginBottom: 28, fontSize: 16 },
  card: { backgroundColor: theme.surface, borderRadius: theme.radius, padding: 20, borderWidth: 1, borderColor: theme.border },
  label: { color: theme.muted, marginBottom: 8, marginTop: 8, fontSize: 13 },
  input: { backgroundColor: theme.surfaceAlt, borderRadius: 12, padding: 16, color: theme.text, fontSize: 16, borderWidth: 1, borderColor: theme.border },
  otp: { letterSpacing: 8, textAlign: "center", fontSize: 24 },
  btn: { backgroundColor: theme.accent, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 18 },
  btnText: { color: "#04120E", fontWeight: "800", fontSize: 16 },
  link: { color: theme.accent, textAlign: "center", marginTop: 16 },
  err: { color: theme.danger, marginTop: 14, textAlign: "center" },
});
