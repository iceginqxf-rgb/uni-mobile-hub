<template>
  <transition name="cd-fade">
    <div v-if="state.open" class="cd-backdrop" @click.self="cancel" @keydown.esc="cancel">
      <div :role="state.mode === 'prompt' ? 'dialog' : 'alertdialog'" class="cd-box" aria-modal="true" :aria-label="state.message">
        <p v-if="state.message" class="cd-msg">{{ state.message }}</p>
        <input
          v-if="state.mode === 'prompt'"
          ref="inputEl"
          v-model="state.value"
          :type="state.password ? 'password' : 'text'"
          :placeholder="state.placeholder"
          class="cd-input"
          @keyup.enter="confirm"
        />
        <div class="cd-actions">
          <button ref="cancelBtn" class="cd-btn" @click="cancel">
            {{ state.cancelText || t("common.cancel") }}
          </button>
          <button class="cd-btn cd-primary" :class="{ danger: state.danger }" @click="confirm">
            {{ state.confirmText || t("common.confirm") }}
          </button>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, watch, nextTick } from "vue";
import { useConfirm } from "../composables/useConfirm";
import { useUiI18n } from "../composables/useUiI18n";

const { state, confirm, cancel } = useConfirm();
const { t } = useUiI18n();
const cancelBtn = ref(null);
const inputEl = ref(null);

watch(
  () => state.open,
  (open) => {
    if (!open) return;
    nextTick(() => {
      if (state.mode === "prompt") {
        const el = inputEl.value;
        el?.focus();
        el?.select?.();
      } else {
        cancelBtn.value?.focus();
      }
    });
  }
);
</script>

<style scoped>
.cd-backdrop {
  position: fixed; inset: 0; z-index: 1100;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.56); backdrop-filter: blur(3px); padding: 20px;
}
.cd-box {
  width: 100%; max-width: 360px; padding: 16px 16px 14px;
  background: var(--panel-solid); border: 1px solid var(--border-strong);
  border-radius: 0; box-shadow: var(--shadow);
  animation: cd-in 0.14s ease;
}
.cd-msg {
  margin: 0 0 12px; font-size: 0.88rem; line-height: 1.5; color: var(--text);
  white-space: pre-line;
}
.cd-input {
  width: 100%; height: 34px; min-height: 34px; padding: 0 10px; margin: 0 0 14px;
  border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--inset); color: var(--text); font-size: 0.88rem;
}
.cd-input:focus { outline: none; border-color: var(--primary); }
.cd-actions { display: flex; justify-content: flex-end; gap: 8px; }
.cd-btn { min-width: 70px; min-height: 30px; padding: 4px 12px; border-radius: 0; font-size: 0.82rem; }
.cd-primary { border-color: var(--primary); background: var(--primary); color: var(--primary-fg); }
.cd-primary:hover { filter: brightness(1.08); }
.cd-primary.danger { border-color: var(--danger); background: var(--danger); color: #fff; }
@keyframes cd-in { from { opacity: 0; transform: translateY(6px) scale(0.98); } to { opacity: 1; transform: none; } }
.cd-fade-enter-active, .cd-fade-leave-active { transition: opacity 0.14s ease; }
.cd-fade-enter-from, .cd-fade-leave-to { opacity: 0; }
</style>
