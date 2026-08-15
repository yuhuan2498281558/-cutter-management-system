<template>
  <el-select
    v-model="innerValue"
    placeholder="请选择开仓位置地质情况"
    filterable
    clearable
    style="width: 100%"
    @change="handleChange"
  >
    <el-option
      v-for="opt in options"
      :key="opt.value"
      :label="opt.label"
      :value="opt.value"
    />
  </el-select>
</template>

<script lang="ts" setup>
import { ref, watch, onMounted } from 'vue';
import { request } from '/@/utils/service';

const props = defineProps<{ modelValue?: string }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();

const innerValue = ref(props.modelValue ?? '');
const options = ref<{ label: string; value: string }[]>([]);

watch(
  () => props.modelValue,
  (v) => { innerValue.value = v ?? ''; }
);

const handleChange = (v: string) => emit('update:modelValue', v);

onMounted(async () => {
  try {
    const res = await request({
      url: '/api/init/dictionary/',
      method: 'get',
      params: { dictionary_key: 'stratum_type' },
    });
    if (res.data) {
      options.value = res.data.map((item: any) => ({
        label: item.label,
        value: item.label,
      }));
    }
  } catch {}
});
</script>
