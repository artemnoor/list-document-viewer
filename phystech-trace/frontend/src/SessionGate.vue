<script setup lang="ts">
import { onMounted, ref } from "vue";
import App from "./App.vue";
const ready = ref(false);
const error = ref("");
async function loadSession() {
  error.value = "";
  try {
    const response = await fetch("/api/auth/me", { cache: "no-store" });
    if (response.status === 401) {
      location.replace(`/logIn?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
      return;
    }
    if (!response.ok) throw new Error("Не удалось открыть кабинет. Попробуйте ещё раз.");
    const { user } = await response.json();
    localStorage.setItem("trace-user-id", user.id);
    localStorage.setItem("trace-profile-name", localStorage.getItem(`trace-profile-name:${user.id}`) || user.name);
    ready.value = true;
  } catch {
    error.value = "Не удалось подключиться к серверу. Попробуйте ещё раз.";
  }
}
onMounted(loadSession);
</script>

<template>
  <App v-if="ready" />
  <main v-else class="session-state" aria-live="polite">
    <p>{{ error || 'Открываем кабинет…' }}</p>
    <button v-if="error" @click="loadSession">Повторить</button>
    <a href="/">На главную</a>
  </main>
</template>

<style scoped>
.session-state { min-height:100vh; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px; }
.session-state button { padding:12px 24px; border:0; border-radius:8px; background:#b4e66b; cursor:pointer; }
</style>
