<template>
  <div class="toasts" aria-live="polite" aria-atomic="false">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type" role="status">
      {{ t.text }}
    </div>
  </div>
</template>

<script setup>
import { useToast } from "../composables/useToast";
const { toasts } = useToast();
</script>

<style scoped>
.toasts {
  position: fixed; right: 14px; bottom: 14px; z-index: 1000;
  display: flex; flex-direction: column; gap: 6px; pointer-events: none;
}
.toast {
  min-width: 150px; max-width: 340px; padding: 8px 12px; border-radius: 0;
  font-size: 0.8rem; color: var(--text-strong);
  background: var(--panel-solid); border: 1px solid var(--border-strong);
  box-shadow: var(--shadow); animation: toast-in .16s ease;
}
.toast.ok { border-left: 3px solid var(--ok); }
.toast.err { border-left: 3px solid var(--danger); }
@keyframes toast-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
</style>
