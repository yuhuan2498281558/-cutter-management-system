<template>
  <div class="input-container">
    <div class="input-inner">
    <div class="toolbar-row" :class="{ model: routeMode === 'agent' }">
      <div class="route-segment">
        <button
          :class="['segment-option', { active: routeMode === 'rule' }]"
          :disabled="loading"
          title="规则路径：快速查询"
          @click="handleSwitchRoute('rule')"
        >
          规则路径
        </button>
        <button
          :class="['segment-option', { active: routeMode === 'agent' }]"
          :disabled="loading"
          title="模型路径：复杂分析"
          @click="handleSwitchRoute('agent')"
        >
          模型路径
        </button>
      </div>

      <!-- 规则路径快捷问题选择 -->
      <template v-if="routeMode === 'rule'">
        <el-select
          v-model="activeQuickGroup"
          class="mode-select"
          size="small"
          :disabled="loading"
          @change="handleQuickGroupChange"
        >
          <el-option
            v-for="group in quickQuestionGroups"
            :key="group.title"
            :label="group.title"
            :value="group.title"
          />
        </el-select>
        <el-select
          v-model="activeQuickItemLabel"
          class="question-select"
          size="small"
          filterable
          :disabled="loading"
          :placeholder="selectedQuickGroup.desc"
        >
          <el-option
            v-for="item in selectedQuickGroup.items"
            :key="item.label"
            :label="buildQuickLabel(item)"
            :value="item.label"
          />
        </el-select>
        <el-input-number
          v-if="selectedQuickItem?.numKey"
          v-model="quickParams[selectedQuickItem.numKey]"
          class="quick-number"
          :min="selectedQuickItem.min || 1"
          :max="selectedQuickItem.max || 200"
          :step="selectedQuickItem.step || 1"
          size="small"
          controls-position="right"
          :disabled="loading"
        />
        <el-button
          class="quick-run"
          type="primary"
          size="small"
          :disabled="loading"
          @click="applyQuickQuestion"
        >
          生成问题
        </el-button>
      </template>

      <!-- 模型路径分析模板与能力选择 -->
      <template v-else>
        <el-select
          v-model="selectedModelDataTypes"
          class="model-capability-select"
          size="small"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="2"
          :disabled="loading"
          placeholder="选择可查数据"
          @change="handleModelDataTypesChange"
        >
          <el-option
            v-for="item in modelDataTypes"
            :key="item"
            :label="item"
            :value="item"
          />
        </el-select>
        <el-select
          v-model="selectedModelPrompt"
          class="model-prompt-select"
          size="small"
          filterable
          :disabled="loading"
          placeholder="选择分析模板"
          @change="composeModelQuestion"
        >
          <el-option
            v-for="item in modelPromptOptions"
            :key="item"
            :label="item"
            :value="item"
          />
        </el-select>
      </template>
    </div>

    <el-input
      ref="inputRef"
      v-model="inputText"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 6 }"
      resize="none"
      :placeholder="routeMode === 'rule' ? '输入规则查询，例如：统计最近100环的换刀情况' : '输入复杂分析问题，可结合多个数据类型追问原因和建议'"
      @keydown.enter="handleEnterKey"
    />

    <div class="input-actions">
      <span class="input-tip">
        {{ routeMode === 'rule' ? '规则路径：下拉选择后可直接生成问题' : '模型路径：选择数据能力与分析模板后自动填入' }} · Enter 发送，Shift + Enter 换行
      </span>
      <div class="button-group">
        <el-button
          v-if="loading"
          type="danger"
          plain
          size="default"
          @click="$emit('abort')"
        >
          停止生成
        </el-button>
        <el-button
          type="primary"
          size="default"
          :loading="loading"
          @click="handleSend"
        >
          发送
        </el-button>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { InputInstance } from 'element-plus';
import { QuickParams, QuickQuestionGroup, QuickQuestionItem, RouteMode } from '../types';
import { defaultModelPrompts, modelDataTypes, modelPromptLibrary, quickQuestionGroups } from '../constants';

const props = defineProps<{
  loading: boolean;
  routeMode: RouteMode;
}>();

const emit = defineEmits<{
  (e: 'send', query: string): void;
  (e: 'update:routeMode', mode: RouteMode): void;
  (e: 'abort'): void;
}>();

const inputText = ref('');
const inputRef = ref<InputInstance>();
const activeQuickGroup = ref(quickQuestionGroups[0].title);

// 生成问题后聚焦输入框并把光标移到末尾，用户可直接按 Enter 发送
const focusInputEnd = () => {
  nextTick(() => {
    inputRef.value?.focus();
    const textareaEl = inputRef.value?.textarea;
    if (textareaEl) {
      const len = textareaEl.value.length;
      textareaEl.setSelectionRange(len, len);
    }
  });
};
const activeQuickItemLabel = ref(quickQuestionGroups[0].items[0].label);

const quickParams = ref<QuickParams>({
  openingLimit: 5,
  ringWindow: 100,
  topN: 10,
  interval: 50,
});

const selectedModelDataTypes = ref<string[]>(['换刀/旧刀补录', '地层信息']);
const selectedModelPrompt = ref('');

const selectedQuickGroup = computed<QuickQuestionGroup>(() => {
  return quickQuestionGroups.find((g) => g.title === activeQuickGroup.value) || quickQuestionGroups[0];
});

const selectedQuickItem = computed<QuickQuestionItem | undefined>(() => {
  return selectedQuickGroup.value.items.find((item) => item.label === activeQuickItemLabel.value);
});

const modelPromptOptions = computed(() => {
  const prompts = selectedModelDataTypes.value.flatMap((type) => modelPromptLibrary[type] || []);
  return Array.from(new Set(prompts.length ? prompts : defaultModelPrompts));
});

const getQuickNumber = (item: QuickQuestionItem) => (item.numKey ? quickParams.value[item.numKey] : undefined);

const buildQuickLabel = (item: QuickQuestionItem) => {
  const num = getQuickNumber(item);
  return num === undefined ? item.label : item.label.replace('{n}', String(num));
};

const buildQuickQuery = (item: QuickQuestionItem) => {
  const num = getQuickNumber(item);
  return num === undefined ? item.query : item.query.replaceAll('{n}', String(num));
};

const handleQuickGroupChange = () => {
  activeQuickItemLabel.value = selectedQuickGroup.value.items[0]?.label || '';
};

const applyQuickQuestion = () => {
  if (!selectedQuickItem.value) return;
  inputText.value = buildQuickQuery(selectedQuickItem.value);
  focusInputEnd();
};

const composeModelQuestion = () => {
  const types = selectedModelDataTypes.value.length ? selectedModelDataTypes.value.join('、') : '相关';
  const template = selectedModelPrompt.value || modelPromptOptions.value[0] || '分析近期异常磨损的主要原因，并给出重点关注刀位和处理建议';
  inputText.value = /^(结合|综合)/.test(template) ? template : `结合${types}数据，${template}`;
  focusInputEnd();
};

const handleModelDataTypesChange = () => {
  if (selectedModelPrompt.value && !modelPromptOptions.value.includes(selectedModelPrompt.value)) {
    selectedModelPrompt.value = modelPromptOptions.value[0] || '';
  }
  composeModelQuestion();
};

const handleSwitchRoute = (mode: RouteMode) => {
  emit('update:routeMode', mode);
  if (mode === 'agent') {
    if (!selectedModelPrompt.value) selectedModelPrompt.value = modelPromptOptions.value[0] || '';
    composeModelQuestion();
  }
};

const handleSend = () => {
  const query = inputText.value.trim();
  if (!query || props.loading) return;
  emit('send', query);
  inputText.value = '';
};

// Enter 直接发送；Shift+Enter 保留换行。生成中允许继续输入，仅拦截发送。
const handleEnterKey = (event: Event) => {
  const keyboardEvent = event as KeyboardEvent;
  if (keyboardEvent.shiftKey || keyboardEvent.isComposing) return;
  keyboardEvent.preventDefault();
  handleSend();
};
</script>

<style scoped lang="scss">
.input-container {
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;

  // 与消息区内容列同宽对齐
  .input-inner {
    width: 100%;
    max-width: 1440px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .toolbar-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;

    .route-segment {
      flex-shrink: 0;
      display: inline-flex;
      padding: 2px;
      background: #f0f2f5;
      border-radius: 6px;

      .segment-option {
        border: none;
        background: transparent;
        border-radius: 5px;
        padding: 4px 12px;
        font-size: 12px;
        font-weight: 600;
        color: #606266;
        cursor: pointer;
        transition: all 0.15s ease;

        &:hover:not(:disabled):not(.active) {
          color: #409eff;
        }

        &.active {
          background: #fff;
          color: #409eff;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        &:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
      }
    }

    .mode-select {
      width: 130px;
    }

    .question-select {
      flex: 1;
      min-width: 180px;
    }

    .quick-number {
      width: 90px;
    }

    .quick-run {
      flex-shrink: 0;
    }

    &.model {
      .model-capability-select {
        width: 180px;
      }

      .model-prompt-select {
        flex: 1;
        min-width: 220px;
      }
    }
  }

  .input-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .input-tip {
      font-size: 12px;
      color: #909399;
    }

    .button-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
  }
}
</style>
