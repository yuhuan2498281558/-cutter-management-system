<template>
  <div class="input-container">
    <div class="input-inner">
    <div class="toolbar-row" :class="{ model: routeMode === 'agent' }">
      <div class="route-segment">
        <button
          :class="['segment-option', { active: routeMode === 'rule' }]"
          :disabled="disabled"
          title="规则路径：快速查询"
          @click="handleSwitchRoute('rule')"
        >
          规则路径
        </button>
        <button
          :class="['segment-option', { active: routeMode === 'agent' }]"
          :disabled="disabled"
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
          :disabled="disabled"
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
          :disabled="disabled"
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
          v-if="selectedQuickItem?.numKey && selectedQuickParams"
          v-model="selectedQuickParams.n"
          class="quick-number"
          :min="selectedQuickItem.min || 1"
          :max="selectedQuickItem.max || 200"
          :step="selectedQuickItem.step || 1"
          size="small"
          controls-position="right"
          :disabled="disabled"
        />
        <el-input
          v-if="selectedQuickItem?.textKey && selectedQuickParams"
          v-model="selectedQuickParams.id"
          class="quick-text"
          size="small"
          placeholder="刀具编号"
          :disabled="disabled"
        />
        <el-button
          class="quick-run"
          type="primary"
          size="small"
          :disabled="disabled || Boolean(quickParamHint)"
          @click="applyQuickQuestion"
        >
          生成问题
        </el-button>
        <span v-if="quickParamHint" class="quick-hint">{{ quickParamHint }}</span>
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
          :disabled="disabled"
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
          :disabled="disabled"
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
      :maxlength="MAX_QUERY_LENGTH"
      show-word-limit
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
          v-if="generating"
          type="danger"
          plain
          size="default"
          @click="$emit('abort')"
        >
          停止生成
        </el-button>
        <!-- 生成中已由 loading 禁用，不再叠加禁用样式；重置等其他禁用时不转圈 -->
        <el-button
          type="primary"
          size="default"
          :loading="generating"
          :disabled="disabled && !generating"
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
import { QuestionParamValues, QuickQuestionGroup, QuickQuestionItem, RouteMode } from '../types';
import { defaultModelPrompts, modelDataTypes, modelPromptLibrary, quickQuestionGroups } from '../constants';

const props = defineProps<{
  // 正在生成回答：显示"停止生成"，发送按钮转圈
  generating: boolean;
  // 生成或重置期间：禁用所有控件
  disabled: boolean;
  routeMode: RouteMode;
}>();

const emit = defineEmits<{
  (e: 'send', query: string): void;
  (e: 'update:routeMode', mode: RouteMode): void;
  (e: 'abort'): void;
}>();

// 与后端 views.py _validate_body 的上限一致
const MAX_QUERY_LENGTH = 10000;

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

// 每条快捷问题各自保存参数，按标签索引（同一种数字在不同问题里的默认值可能不同）
const quickParams = ref<Record<string, QuestionParamValues>>(Object.fromEntries(
  quickQuestionGroups.flatMap((group) => group.items).map((item) => [item.label, { n: item.defaultValue ?? null, id: '' }])
));

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

const selectedQuickParams = computed(() => (selectedQuickItem.value ? quickParams.value[selectedQuickItem.value.label] : undefined));

// 数字框清空时 Element Plus 给的是 null，按"未填写"处理，不把 null 写进问题
const getQuickNumber = (item: QuickQuestionItem) => {
  const num = item.numKey ? quickParams.value[item.label]?.n : undefined;
  return Number.isFinite(num) ? (num as number) : undefined;
};

const getQuickId = (item: QuickQuestionItem) => (item.textKey ? quickParams.value[item.label]?.id.trim() || '' : '');

// 参数没填时说明为什么不能生成问题；为空字符串表示可以生成
const quickParamHint = computed(() => {
  const item = selectedQuickItem.value;
  if (item?.numKey && getQuickNumber(item) === undefined) return '请先填写数字';
  if (item?.textKey && !getQuickId(item)) return '请先填写刀具编号';
  return '';
});

const buildQuickLabel = (item: QuickQuestionItem) => {
  const num = getQuickNumber(item);
  return item.label.replace('{n}', num === undefined ? 'N' : String(num));
};

// 只在参数都已填写（quickParamHint 为空）时调用
const buildQuickQuery = (item: QuickQuestionItem) => item.query
  .replaceAll('{n}', String(getQuickNumber(item)))
  .replaceAll('{id}', getQuickId(item));

const handleQuickGroupChange = () => {
  activeQuickItemLabel.value = selectedQuickGroup.value.items[0]?.label || '';
};

// 上次自动填入的问题。输入框为空或仍是这段文字时才自动替换，用户写过或改过的草稿保留。
let lastAutoFilled = '';
const fillInput = (text: string) => {
  inputText.value = text;
  lastAutoFilled = text;
  focusInputEnd();
};
const canAutoFill = () => !inputText.value.trim() || inputText.value === lastAutoFilled;

const applyQuickQuestion = () => {
  if (!selectedQuickItem.value || quickParamHint.value) return;
  fillInput(buildQuickQuery(selectedQuickItem.value));
};

const composeModelQuestion = () => {
  const types = selectedModelDataTypes.value.length ? selectedModelDataTypes.value.join('、') : '相关';
  const template = selectedModelPrompt.value || modelPromptOptions.value[0] || '分析近期异常磨损的主要原因，并给出重点关注刀位和处理建议';
  fillInput(/^(结合|综合)/.test(template) ? template : `结合${types}数据，${template}`);
};

const handleModelDataTypesChange = () => {
  if (selectedModelPrompt.value && !modelPromptOptions.value.includes(selectedModelPrompt.value)) {
    selectedModelPrompt.value = modelPromptOptions.value[0] || '';
  }
  if (canAutoFill()) composeModelQuestion();
};

const handleSwitchRoute = (mode: RouteMode) => {
  if (mode === props.routeMode) return;
  emit('update:routeMode', mode);
  if (mode === 'agent') {
    if (!selectedModelPrompt.value) selectedModelPrompt.value = modelPromptOptions.value[0] || '';
    if (canAutoFill()) composeModelQuestion();
  }
};

const handleSend = () => {
  const query = inputText.value.trim();
  if (!query || props.disabled) return;
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

    .quick-text {
      width: 140px;
    }

    .quick-run {
      flex-shrink: 0;
    }

    .quick-hint {
      font-size: 12px;
      color: #e6a23c;
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
