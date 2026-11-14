<script setup lang="ts">
import type { VerificationScope } from '../types';
const props = defineProps<{ modelValue: VerificationScope; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [scope: VerificationScope] }>();
function update(key: keyof VerificationScope, event: Event) {
  emit('update:modelValue', { ...props.modelValue, [key]: (event.target as HTMLInputElement).value || null });
}
</script>
<template>
  <fieldset class="verification-scope" :disabled="disabled">
    <legend>Что проверяем</legend>
    <label class="form-label">Способ проверки<select :value="modelValue.calculation_mode || 'auto'" @change="update('calculation_mode', $event)"><option value="auto">Автоматически: статьи затрат по реквизитам и содержанию</option><option value="semantic">Расширенный поиск связей через модель</option></select></label>
    <label class="form-label">Строка или этап отчёта<input :value="modelValue.report_row || ''" maxlength="200" placeholder="Например, 3 этап 2026" @input="update('report_row', $event)" /></label>
    <p>Оставьте строку пустой, чтобы проверить весь отчёт.</p>
    <div class="scope-dates">
      <label class="form-label">Начало периода<input type="date" :value="modelValue.period_start || ''" @input="update('period_start', $event)" /></label>
      <label class="form-label">Конец периода<input type="date" :value="modelValue.period_end || ''" @input="update('period_end', $event)" /></label>
    </div>
  </fieldset>
</template>
<style scoped>
.verification-scope { border: 0; padding: 0; margin: 24px 0 0; min-width: 0; }
legend { font-weight: 600; margin-bottom: 12px; }
p { font-size: 12px; color: #626868; margin: 8px 0 14px; }
.scope-dates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
</style>
