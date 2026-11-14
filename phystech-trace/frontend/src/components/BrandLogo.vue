<script setup lang="ts">
const logoUrl = `${import.meta.env.BASE_URL}brand/phystech-trace.png`;
</script>

<template>
  <svg class="brand-logo" viewBox="92 176 1958 374" role="img" aria-label="Phystech Trace">
    <image :href="logoUrl" width="2137" height="736" />
  </svg>
</template>

<style scoped>
.brand-logo { display:block; width:100%; height:auto; overflow:hidden; filter:brightness(0); }
</style>
