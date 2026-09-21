<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import LoginView from './views/LoginView.vue'
import RegisterView from './views/RegisterView.vue'
import PendingView from './views/PendingView.vue'
import AdminView from './views/AdminView.vue'
import SettingsView from './views/SettingsView.vue'
import { auth, isAdmin, isLoggedIn, restoreSession } from './auth'

type Page = 'login' | 'register' | 'pending' | 'admin' | 'settings'

const currentPage = ref<Page>('login')
const restoring = ref(true)

async function init() {
  const ok = await restoreSession()
  if (ok) {
    routeByRole()
  } else {
    currentPage.value = 'login'
  }
  restoring.value = false
}

function routeByRole() {
  if (isAdmin()) {
    currentPage.value = 'admin'
  } else {
    currentPage.value = 'pending'
  }
}

function onLoggedIn() {
  routeByRole()
}

function onLoggedOut() {
  currentPage.value = 'login'
}

function onRegistered() {
  currentPage.value = 'login'
}

function onProfileUpdated() {
  restoreSession()
}

function onPasswordChanged() {
  currentPage.value = 'login'
}

function onGoBack() {
  routeByRole()
}

function onAuthRequired() {
  currentPage.value = 'login'
}

onMounted(() => {
  window.addEventListener('auth:required', onAuthRequired)
  init()
})

onUnmounted(() => {
  window.removeEventListener('auth:required', onAuthRequired)
})
</script>

<template>
  <div v-loading="restoring" class="app">
    <LoginView
      v-if="currentPage === 'login'"
      @logged-in="onLoggedIn"
      @go-register="currentPage = 'register'"
    />
    <RegisterView
      v-else-if="currentPage === 'register'"
      @registered="onRegistered"
      @go-login="currentPage = 'login'"
    />
    <PendingView
      v-else-if="currentPage === 'pending'"
      @go-settings="currentPage = 'settings'"
      @logged-out="onLoggedOut"
    />
    <AdminView
      v-else-if="currentPage === 'admin'"
      @go-settings="currentPage = 'settings'"
      @logged-out="onLoggedOut"
    />
    <SettingsView
      v-else-if="currentPage === 'settings'"
      @profile-updated="onProfileUpdated"
      @password-changed="onPasswordChanged"
      @logged-out="onLoggedOut"
      @go-back="onGoBack"
    />
  </div>
</template>

<style>
body { margin: 0; background: #f5f7fa; color: #303133; font-family: system-ui, sans-serif; }
.app { padding: 24px; min-height: 100vh; }
</style>
