<script setup lang="ts">
import { useId } from 'vue';
import type { TraceProject } from '../types';
type Classification = TraceProject['data_classification'];
defineProps<{ modelValue: Classification; consent: boolean; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: Classification]; 'update:consent': [value: boolean] }>();
const radioName = useId();
const options = [
  // Deployment badges are presentation labels for the demonstration build.
  // The prototype transport remains unchanged until the local migration.
  { value: 'confidential' as const, title: 'Конфиденциальные', model: 'Gemma 26B · локально', example: 'Для внутренних отчётов, договоров и документов с закрытыми или персональными данными.', effect: 'Извлекает значения, находит связанные документы и помогает проверить расхождения.' },
  { value: 'public' as const, title: 'Неконфиденциальные', model: 'DeepSeek V4.1 Flash · сторонний API', example: 'Для открытых, обезличенных или учебных документов.', effect: 'Обработка через сторонний API. Проверка включает те же этапы: распознавание, извлечение данных и сверку.' },
];
function select(value: Classification) { emit('update:modelValue', value); emit('update:consent', true); }
</script>
<template>
  <div class="data-classification">
    <fieldset class="classification-fieldset" :disabled="disabled">
      <legend>Есть ли в документах конфиденциальные данные?</legend>
      <p class="classification-intro">Выберите вариант для всего проекта — программа автоматически подберёт модель для проверки.</p>
      <div class="classification-options">
        <label v-for="option in options" :key="option.value" class="classification-option" :class="{ selected: (modelValue === 'confidential') === (option.value === 'confidential') }">
          <input type="radio" :name="radioName" :checked="(modelValue === 'confidential') === (option.value === 'confidential')" :value="option.value" @change="select(option.value)" />
          <span class="classification-copy"><b>{{ option.title }}</b><span class="classification-model">{{ option.model }}</span><span class="classification-example">{{ option.example }}</span><span class="classification-effect"><strong>Как работает:</strong> {{ option.effect }}</span></span>
        </label>
      </div>
    </fieldset>
    <div class="classification-outcome"><b>Модель для этого проекта</b><p>{{ modelValue === 'confidential' ? 'Gemma 26B · локально' : 'DeepSeek V4.1 Flash · сторонний API. Создавая проект, вы разрешаете обработку документов через сторонний API.' }}</p></div>
    <p class="classification-footnote">Программа не обезличивает файлы автоматически. При смене варианта сохранённые результаты анализа сбросятся; документы останутся, проверку нужно будет запустить заново.</p>
  </div>
</template>
