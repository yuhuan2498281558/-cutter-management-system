<template>
  <div class="stratum-info-input">
    <div v-for="(item, index) in localValue" :key="index" class="stratum-item">
      <el-select
        v-model="item.stratum_type_code"
        placeholder="请选择地层类型"
        filterable
        style="width: 200px; margin-right: 10px"
        @change="handleStratumTypeChange(index)"
      >
        <el-option
          v-for="option in stratumTypeOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-input-number
        v-model="item.ring_count"
        :min="0"
        :precision="0"
        placeholder="环数"
        style="width: 150px; margin-right: 10px"
        @change="handleChange"
      />
      <el-button type="danger" icon="Delete" circle @click="removeItem(index)" />
    </div>
    <el-button type="primary" icon="Plus" @click="addItem" style="margin-top: 10px">
      添加地层类型
    </el-button>
  </div>
</template>

<script lang="ts" setup>
import { ref, watch, onMounted } from 'vue';
import { request } from '/@/utils/service';

interface StratumInfoItem {
  stratum_type_code: string;
  stratum_type_name?: string;
  ring_count: number;
}

interface StratumTypeOption {
  label: string;
  value: string;
}

const props = defineProps<{
  modelValue?: StratumInfoItem[];
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: StratumInfoItem[]): void;
}>();

const localValue = ref<StratumInfoItem[]>([]);
const stratumTypeOptions = ref<StratumTypeOption[]>([]);

// 加载地层类型选项
const loadStratumTypes = async () => {
  try {
    const response = await request({
      url: '/api/init/dictionary/',
      method: 'get',
      params: { dictionary_key: 'stratum_type' },
    });
    if (response.data) {
      stratumTypeOptions.value = response.data.map((item: any) => ({
        label: item.label,
        value: item.value,
      }));
    }
  } catch (error) {
    console.error('加载地层类型失败:', error);
  }
};

// 添加新项
const addItem = () => {
  localValue.value.push({
    stratum_type_code: '',
    ring_count: 0,
  });
};

// 删除项
const removeItem = (index: number) => {
  localValue.value.splice(index, 1);
  handleChange();
};

// 处理地层类型变化
const handleStratumTypeChange = (index: number) => {
  const selectedOption = stratumTypeOptions.value.find(
    (opt) => opt.value === localValue.value[index].stratum_type_code
  );
  if (selectedOption) {
    localValue.value[index].stratum_type_name = selectedOption.label;
  }
  handleChange();
};

// 处理值变化
const handleChange = () => {
  emit('update:modelValue', localValue.value);
};

// 监听外部值变化
watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue && Array.isArray(newValue)) {
      localValue.value = JSON.parse(JSON.stringify(newValue));
    } else {
      localValue.value = [];
    }
  },
  { immediate: true, deep: true }
);

onMounted(() => {
  loadStratumTypes();
});
</script>

<style scoped>
.stratum-info-input {
  width: 100%;
}

.stratum-item {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}
</style>
