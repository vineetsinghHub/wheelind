import React from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { StatusBar } from "expo-status-bar";
import { NavigationContainer, DefaultTheme } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AuthProvider, useAuth } from "./src/context/AuthContext";
import { theme } from "./src/theme";
import AuthScreen from "./src/screens/AuthScreen";
import DashboardScreen from "./src/screens/DashboardScreen";

const Stack = createNativeStackNavigator();
const navTheme = { ...DefaultTheme, colors: { ...DefaultTheme.colors, background: theme.bg } };

function Root() {
  const { user } = useAuth();
  if (user === undefined) return <View style={s.center}><ActivityIndicator color={theme.accent} /></View>;
  return (
    <Stack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: theme.bg } }}>
      {user ? (
        <Stack.Screen name="Dashboard" component={DashboardScreen} />
      ) : (
        <Stack.Screen name="Auth" component={AuthScreen} />
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <NavigationContainer theme={navTheme}>
        <StatusBar style="light" />
        <AuthProvider>
          <Root />
        </AuthProvider>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

const s = StyleSheet.create({ center: { flex: 1, backgroundColor: theme.bg, alignItems: "center", justifyContent: "center" } });
