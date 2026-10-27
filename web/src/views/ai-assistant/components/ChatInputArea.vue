<template>
  <div ref="containerRef" class="input-container">
    <!-- 向上浮出的双栏选词与数据源面板（用完即收，不占常驻高度） -->
    <div v-if="paletteOpen && !disabled" class="floating-palette">
      <template v-if="routeMode === 'rule'">
        <div class="palette-cats">
          <button
            v-for="group in quickQuestionGroups"
            :key="group.title"
            type="button"
            :class="['palette-cat-btn', { active: activeQuickGroup === group.title }]"
            @click="selectQuickGroup(group.title)"
          >
            {{ group.title }}
          </button>
        </div>
        <div class="palette-items">
          <div
            v-for="item in selectedQuickGroup.items"
            :key="item.label"
            :class="['palette-item-row', { active: activeQuickItemLabel === item.label }]"
            @click="pickQuickItem(item)"
          >
            <span class="palette-item-title">{{ buildQuickLabel(item) }}</span>
            <span class="palette-item-sub">{{ item.numKey || item.textKey ? '填入参数后查询' : '点击直接查询' }}</span>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="palette-cats model-sources">
          <div class="palette-section-title">{{ supportsFocusSources ? '限定可查数据' : '按数据类型筛选模板' }}</div>
          <button
            v-for="source in FOCUS_SOURCES"
            :key="source.value"
            type="button"
            :class="['palette-cat-btn', { active: selectedSources.includes(source.value) }]"
            @click="toggleModelSource(source.value)"
          >
            {{ source.label }}
          </button>
        </div>
        <div class="palette-items">
          <div
            v-for="template in visibleTemplates"
            :key="template.title"
            :class="['palette-item-row', { active: selectedTemplateTitle === template.title }]"
            @click="pickModelTemplate(template.title)"
          >
            <span class="palette-item-title">{{ template.title }}</span>
            <span class="palette-item-sub">关联：{{ formatTemplateSources(template.sources) }}</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 聚合单框 Composer -->
    <div class="unified-composer" :class="{ disabled }">
      <!-- 上半部：句内结构化填空态 或 自由文本编辑态 -->
      <div v-if="useTemplateSlot && activeSpec" class="composer-editor">
        <span>{{ activeTemplateParts.prefix }}</span>

        <!-- 数字槽位 -->
        <span v-if="activeSpec.numKey && activeParamValues" class="slot-chip">
          <input
            ref="slotInputRef"
            v-model.number="activeParamValues.n"
            type="number"
            :min="activeSpec.min || 1"
            :max="activeSpec.max || 500"
            :step="activeSpec.step || 1"
            :disabled="disabled"
            @input="syncActiveSlotQuestion"
            @keydown.enter="handleEnterKey"
          />
        </span>

        <!-- 刀型槽位 -->
        <select
          v-else-if="activeSpec.toolParam && activeParamValues"
          v-model="activeParamValues.tool"
          class="slot-select"
          :disabled="disabled"
          @change="syncActiveSlotQuestion"
        >
          <option v-for="tool in TOOL_TYPE_OPTIONS" :key="tool" :value="tool">{{ tool }}</option>
        </select>

        <!-- 刀具编号槽位 -->
        <span v-else-if="activeSpec.textKey && activeParamValues" class="slot-chip slot-id-chip">
          <input
            ref="slotInputRef"
            v-model="activeParamValues.id"
            type="text"
            placeholder="刀具编号"
            :disabled="disabled"
            @input="syncActiveSlotQuestion"
            @keydown.enter="handleEnterKey"
          />
        </span>

        <span>{{ activeTemplateParts.suffix }}</span>

        <button
          type="button"
          class="free-edit-btn"
          :disabled="disabled"
          @click="switchToFreeInput"
        >
          [自由编辑文字]
        </button>
      </div>

      <div v-else class="composer-editor free-mode">
        <el-input
          ref="inputRef"
          v-model="inputText"
          class="composer-textarea"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          :maxlength="MAX_QUERY_LENGTH"
          resize="none"
          :disabled="disabled"
          :placeholder="routeMode === 'rule' ? '输入规则查询，例如：统计最近100环的换刀情况' : '输入复杂分析问题，可结合多个数据类型追问原因和建议'"
          @keydown.enter="handleEnterKey"
        />
        <button
          v-if="activeSpec"
          type="button"
          class="free-edit-btn"
          :disabled="disabled"
          @click="switchToSlotMode"
        >
          [返回模板填空]
        </button>
      </div>

      <!-- 下半部：框内底栏 -->
      <div class="composer-footer">
        <div class="composer-footer-left">
          <div class="seg-pill route-segment">
            <button
              type="button"
              :class="['seg-btn', 'segment-option', { active: routeMode === 'rule' }]"
              :disabled="disabled"
              title="规则路径：直连数据库秒级查询"
              @click="handleSwitchRoute('rule')"
            >
              直连查库 (秒回)
            </button>
            <button
              type="button"
              :class="['seg-btn', 'segment-option', { active: routeMode === 'agent' }]"
              :disabled="disabled"
              title="模型路径：连接大模型 API 深度分析"
              @click="handleSwitchRoute('agent')"
            >
              模型分析 (API)
            </button>
          </div>

          <button
            type="button"
            :class="['trigger-pill', { open: paletteOpen }]"
            :disabled="disabled"
            @click="togglePalette"
          >
            <span v-if="routeMode === 'rule'">
              常用查询：{{ selectedQuickGroup.title }}{{ selectedQuickItem ? ` · ${buildQuickLabel(selectedQuickItem)}` : '' }}
            </span>
            <span v-else>
              分析模板：{{ selectedTemplateTitle || '选择分析模板' }}
            </span>
            <span class="trigger-arrow">{{ paletteOpen ? '收起' : '切换 ▴' }}</span>
          </button>

          <span v-if="routeMode === 'agent' && selectedSources.length" class="sources-summary">
            已选 {{ selectedSources.length }} 类数据
          </span>
        </div>

        <div class="composer-footer-right button-group">
          <span v-if="useTemplateSlot && activeParamHint" class="quick-hint">{{ activeParamHint }}</span>
          <ContextMeter :info="meterInfo" :busy="disabled" @compact="emit('compact')" />
          <el-button
            v-if="generating"
            type="danger"
            plain
            size="small"
            @click="$emit('abort')"
          >
            停止生成
          </el-button>
          <!-- 生成中已由 loading 禁用，不再叠加禁用样式；重置等其他禁用时不转圈 -->
          <el-button
            class="btn-send"
            type="primary"
            size="small"
            :loading="generating"
            :disabled="(disabled && !generating) || (useTemplateSlot && Boolean(activeParamHint))"
            @click="handleSend"
          >
            {{ routeMode === 'rule' ? '查询' : '发送' }}
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import type { InputInstance } from 'element-plus';
import { ContextInfo, FocusSource, ModelPromptTemplate, QuestionParamValues, QuickQuestionGroup, QuickQuestionItem, RouteMode } from '../types';
import { FOCUS_SOURCES, TOOL_TYPE_OPTIONS, modelPromptTemplates, quickQuestionGroups } from '../constants';
import { supportsFocusSources } from '../backendCapabilities';
import ContextMeter from './ContextMeter.vue';

const props = defineProps<{
  // 正在生成回答：显示"停止生成"，发送按钮转圈
  generating: boolean;
  // 生成或重置期间：禁用所有控件
  disabled: boolean;
  routeMode: RouteMode;
  // 上下文用量（估算），由页面从历史接口和每轮回答里拿到
  contextInfo?: ContextInfo | null;
}>();

const emit = defineEmits<{
  (e: 'send', query: string): void;
  (e: 'update:routeMode', mode: RouteMode): void;
  // 模型路径选中的数据类型有变化，页面在模型路径发送时带上
  (e: 'sources-change', sources: FocusSource[]): void;
  (e: 'abort'): void;
  // 在用量面板里点了"整理早前对话"
  (e: 'compact'): void;
}>();

// 与后端 views.py _validate_body 的上限一致
const MAX_QUERY_LENGTH = 10000;

// 直连查库不调用模型：圆环显示灰色，面板只说明对话记忆
const meterInfo = computed<ContextInfo | null>(() => {
  const info = props.contextInfo;
  if (!info || props.routeMode !== 'rule') return info ?? null;
  return { ...info, kind: 'rule', used: null, parts: null, results_raw: null, exceeded: false };
});

const containerRef = ref<HTMLElement>();
const inputText = ref('');
const inputRef = ref<InputInstance>();
const slotInputRef = ref<HTMLInputElement>();
const paletteOpen = ref(false);
// 句内填空态：问题按模板显示，参数在句子里直接填；改成自己写的文字后切到自由编辑态
const useTemplateSlot = ref(true);
const activeQuickGroup = ref(quickQuestionGroups[0].title);
const activeQuickItemLabel = ref(quickQuestionGroups[0].items[0].label);

// 切到自由编辑后聚焦输入框并把光标移到末尾
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

type ParamSpec = Pick<ModelPromptTemplate, 'numKey' | 'textKey' | 'toolParam' | 'defaultValue' | 'min' | 'max' | 'step'> & { query: string };

const initialParams = (spec: Pick<ModelPromptTemplate, 'defaultValue'>): QuestionParamValues => ({
  n: spec.defaultValue ?? null,
  tool: TOOL_TYPE_OPTIONS[0],
  id: '',
});

// 数字框清空时按"未填写"处理，不把 null 写进问题
const paramNumber = (values?: QuestionParamValues) => (Number.isFinite(values?.n) ? (values?.n as number) : undefined);

// 参数没填时说明为什么不能生成问题；为空字符串表示可以生成
const paramHint = (spec?: Partial<ParamSpec>, values?: QuestionParamValues) => {
  if (spec?.numKey && paramNumber(values) === undefined) return '请先填写数字';
  if (spec?.textKey && !values?.id.trim()) return '请先填写刀具编号';
  return '';
};

// 只在参数都已填写（paramHint 为空）时调用
const fillParams = (text: string, values: QuestionParamValues) => text
  .replaceAll('{n}', String(paramNumber(values)))
  .replaceAll('{tool}', values.tool)
  .replaceAll('{id}', values.id.trim());

// 每条快捷问题各自保存参数，按标签索引（同一种数字在不同问题里的默认值可能不同）
const quickParams = ref<Record<string, QuestionParamValues>>(Object.fromEntries(
  quickQuestionGroups.flatMap((group) => group.items).map((item) => [item.label, initialParams(item)])
));

const selectedQuickGroup = computed<QuickQuestionGroup>(() => {
  return quickQuestionGroups.find((g) => g.title === activeQuickGroup.value) || quickQuestionGroups[0];
});

const selectedQuickItem = computed<QuickQuestionItem | undefined>(() => {
  return selectedQuickGroup.value.items.find((item) => item.label === activeQuickItemLabel.value);
});

const selectedQuickParams = computed(() => (selectedQuickItem.value ? quickParams.value[selectedQuickItem.value.label] : undefined));

const quickParamHint = computed(() => paramHint(selectedQuickItem.value, selectedQuickParams.value));

const buildQuickLabel = (item: QuickQuestionItem) => {
  const num = paramNumber(quickParams.value[item.label]);
  return item.label.replace('{n}', num === undefined ? 'N' : String(num));
};

// 模型路径：数据类型过滤模板，模板各自保存参数，按标题索引
const selectedSources = ref<FocusSource[]>([]);
watch(selectedSources, (sources) => emit('sources-change', [...sources]));
const selectedTemplateTitle = ref(modelPromptTemplates.find((t) => t.isDefault)?.title || modelPromptTemplates[0].title);
const templateParams = ref<Record<string, QuestionParamValues>>(Object.fromEntries(
  modelPromptTemplates.map((template) => [template.title, initialParams(template)])
));

// 选了数据类型时只显示和所选类型有交集的模板；一个都没选时显示默认的三条
const visibleTemplates = computed(() => (selectedSources.value.length
  ? modelPromptTemplates.filter((template) => template.sources.some((source) => selectedSources.value.includes(source)))
  : modelPromptTemplates.filter((template) => template.isDefault)));

const selectedTemplate = computed(() => modelPromptTemplates.find((template) => template.title === selectedTemplateTitle.value));
const selectedTemplateParams = computed(() => (selectedTemplate.value ? templateParams.value[selectedTemplate.value.title] : undefined));
const templateParamHint = computed(() => paramHint(selectedTemplate.value, selectedTemplateParams.value));

// 当前路径的模板规格与参数（规则路径是快捷问题，模型路径是分析模板）
const activeSpec = computed<ParamSpec | undefined>(() => (
  props.routeMode === 'rule' ? selectedQuickItem.value : selectedTemplate.value
));

const activeParamValues = computed<QuestionParamValues | undefined>(() => (
  props.routeMode === 'rule' ? selectedQuickParams.value : selectedTemplateParams.value
));

const activeParamHint = computed(() => (
  props.routeMode === 'rule' ? quickParamHint.value : templateParamHint.value
));

// 将模板句子按占位符拆成前后两段，供句内填空渲染
const activeTemplateParts = computed(() => {
  const spec = activeSpec.value;
  if (!spec) return { prefix: '', suffix: '' };
  const token = spec.numKey ? '{n}' : spec.toolParam ? '{tool}' : spec.textKey ? '{id}' : '';
  if (!token || !spec.query.includes(token)) {
    return { prefix: spec.query, suffix: '' };
  }
  const [prefix, ...rest] = spec.query.split(token);
  return { prefix, suffix: rest.join(token) };
});

const formatTemplateSources = (sources: FocusSource[]) => {
  return FOCUS_SOURCES
    .filter((item) => sources.includes(item.value))
    .map((item) => item.label)
    .join(' / ');
};

// 选中模板后自动勾上它关联的数据类型（按数据类型的固定顺序）
const selectTemplate = (title: string) => {
  selectedTemplateTitle.value = title;
  const template = selectedTemplate.value;
  if (!template) return;
  selectedSources.value = FOCUS_SOURCES
    .map((source) => source.value)
    .filter((source) => selectedSources.value.includes(source) || template.sources.includes(source));
};

const handleQuickGroupChange = () => {
  activeQuickItemLabel.value = selectedQuickGroup.value.items[0]?.label || '';
};

// 上次自动填入的问题。输入框为空或仍是这段文字时才自动替换，用户写过或改过的草稿保留。
let lastAutoFilled = '';
const fillInput = (text: string) => {
  lastAutoFilled = text;
  inputText.value = text;
  if (!useTemplateSlot.value) focusInputEnd();
};
const canAutoFill = () => !inputText.value.trim() || inputText.value === lastAutoFilled;

// 用户在自由编辑框里改了自动填入的文字，就停在自由编辑态，不再被模板覆盖
watch(inputText, (val) => {
  if (val.trim() && val !== lastAutoFilled) useTemplateSlot.value = false;
});

const applyQuickQuestion = () => {
  const item = selectedQuickItem.value;
  if (!item || quickParamHint.value) return;
  fillInput(fillParams(item.query, quickParams.value[item.label]));
};

const composeModelQuestion = () => {
  const template = selectedTemplate.value;
  if (!template || templateParamHint.value) return;
  fillInput(fillParams(template.query, templateParams.value[template.title]));
};

const syncActiveSlotQuestion = () => {
  if (props.routeMode === 'rule') applyQuickQuestion();
  else composeModelQuestion();
};

const handleTemplateChange = (title: string) => {
  selectTemplate(title);
  composeModelQuestion();
};

const handleModelDataTypesChange = () => {
  if (!visibleTemplates.value.some((template) => template.title === selectedTemplateTitle.value)) {
    selectedTemplateTitle.value = visibleTemplates.value[0]?.title || '';
  }
  if (canAutoFill()) composeModelQuestion();
};

const togglePalette = () => {
  if (props.disabled) return;
  paletteOpen.value = !paletteOpen.value;
};

const selectQuickGroup = (title: string) => {
  activeQuickGroup.value = title;
  handleQuickGroupChange();
  useTemplateSlot.value = true;
  applyQuickQuestion();
};

// 不带参数的常用查询点了直接发；带参数的先在句子里填参数
const pickQuickItem = (item: QuickQuestionItem) => {
  activeQuickItemLabel.value = item.label;
  useTemplateSlot.value = true;
  paletteOpen.value = false;
  applyQuickQuestion();
  if (!item.numKey && !item.textKey) handleSend();
  else nextTick(() => slotInputRef.value?.focus());
};

const toggleModelSource = (source: FocusSource) => {
  selectedSources.value = selectedSources.value.includes(source)
    ? selectedSources.value.filter((item) => item !== source)
    : FOCUS_SOURCES.map((s) => s.value).filter((v) => v === source || selectedSources.value.includes(v));
  handleModelDataTypesChange();
};

const pickModelTemplate = (title: string) => {
  useTemplateSlot.value = true;
  paletteOpen.value = false;
  handleTemplateChange(title);
  nextTick(() => slotInputRef.value?.focus());
};

const switchToFreeInput = () => {
  if (!inputText.value.trim() && !activeParamHint.value) syncActiveSlotQuestion();
  useTemplateSlot.value = false;
  focusInputEnd();
};

const switchToSlotMode = () => {
  useTemplateSlot.value = true;
  syncActiveSlotQuestion();
};

// 换路径时题库跟着换：输入框里还是自动填的问题（或为空）时，换成新路径当前题目，回到填空态；用户自己写的草稿保留
const handleSwitchRoute = (mode: RouteMode) => {
  if (mode === props.routeMode) return;
  paletteOpen.value = false;
  const autoFill = canAutoFill();
  emit('update:routeMode', mode);
  if (mode === 'agent') selectTemplate(selectedTemplateTitle.value || visibleTemplates.value[0]?.title || '');
  if (!autoFill) return;
  inputText.value = '';
  lastAutoFilled = '';
  useTemplateSlot.value = true;
  if (mode === 'agent') composeModelQuestion();
  else applyQuickQuestion();
};

const handleSend = () => {
  if (props.disabled) return;
  // 填空态下输入框可能还是旧文字，发送前按当前参数重写一遍
  if (useTemplateSlot.value && canAutoFill()) {
    if (activeParamHint.value) return;
    syncActiveSlotQuestion();
  }
  const query = inputText.value.trim();
  if (!query) return;
  paletteOpen.value = false;
  emit('send', query);
  inputText.value = '';
  lastAutoFilled = '';
};

// Enter 直接发送；Shift+Enter 保留换行。生成中允许继续输入，仅拦截发送。
const handleEnterKey = (event: Event) => {
  const keyboardEvent = event as KeyboardEvent;
  if (keyboardEvent.shiftKey || keyboardEvent.isComposing) return;
  keyboardEvent.preventDefault();
  handleSend();
};

// 点面板和输入框以外的地方收起面板
const handleDocumentClick = (event: MouseEvent) => {
  if (!paletteOpen.value) return;
  const target = event.target as Node | null;
  if (containerRef.value && target && !containerRef.value.contains(target)) paletteOpen.value = false;
};

onMounted(() => document.addEventListener('mousedown', handleDocumentClick));
onUnmounted(() => document.removeEventListener('mousedown', handleDocumentClick));
</script>

<style scoped lang="scss">
.input-container {
  position: relative;
  padding: 10px 16px 14px;
  background: var(--dv-surface);

  // 去掉数字框自带的上下箭头，数字在填空块里居中
  input[type='number']::-webkit-inner-spin-button,
  input[type='number']::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  input[type='number'] {
    -moz-appearance: textfield;
    appearance: textfield;
  }
}

/* 向上浮出的双栏选词面板 */
.floating-palette {
  position: absolute;
  left: 16px;
  bottom: calc(100% - 2px);
  width: 560px;
  max-width: calc(100% - 32px);
  background: var(--dv-surface);
  border: 1px solid var(--dv-border-strong);
  border-radius: var(--dv-radius-popover);
  box-shadow: var(--dv-shadow-overlay);
  display: flex;
  overflow: hidden;
  z-index: 30;

  .palette-cats {
    width: 140px;
    flex-shrink: 0;
    background: var(--dv-tile);
    border-right: 1px solid var(--dv-border);
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 240px;
    overflow-y: auto;

    .palette-section-title {
      padding: 4px 10px;
      font-size: 12px;
      color: var(--dv-text-muted);
      font-weight: 500;
    }

    .palette-cat-btn {
      height: 28px;
      padding: 0 10px;
      border: none;
      border-radius: var(--dv-radius-badge);
      background: transparent;
      text-align: left;
      font-size: 12.5px;
      color: var(--dv-text-regular);
      cursor: pointer;
      transition: all 0.12s ease;
      flex-shrink: 0;

      &:hover {
        background: var(--dv-hover);
      }

      &.active {
        background: var(--dv-surface);
        color: var(--dv-accent-strong);
        font-weight: 600;
        box-shadow: var(--dv-shadow-1);
      }
    }
  }

  .palette-items {
    flex: 1;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 240px;
    overflow-y: auto;

    .palette-item-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 7px 10px;
      border-radius: var(--dv-radius-seg-sm);
      cursor: pointer;
      transition: background 0.12s ease;

      &:hover {
        background: var(--dv-hover);
      }

      &.active {
        background: var(--dv-accent-soft);
      }

      .palette-item-title {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--dv-text);
      }

      .palette-item-sub {
        font-size: 12px;
        color: var(--dv-text-secondary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
    }
  }
}

/* 聚合单框 Composer */
.unified-composer {
  background: var(--dv-surface);
  border: 1px solid var(--dv-border-strong);
  border-radius: var(--dv-radius-popover);
  padding: 10px 12px 8px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 8px;

  &:focus-within {
    border-color: var(--dv-accent);
    box-shadow: 0 0 0 3px var(--dv-accent-soft);
  }

  &.disabled {
    opacity: 0.72;
  }
}

/* 句内结构化填空 / 自由输入编辑区 */
.composer-editor {
  min-height: 28px;
  font-size: 13.5px;
  line-height: 26px;
  color: var(--dv-text);
  word-break: break-word;

  &.free-mode {
    display: flex;
    align-items: flex-start;
    gap: 8px;

    .composer-textarea {
      flex: 1;

      :deep(.el-textarea__inner) {
        border: none !important;
        box-shadow: none !important;
        padding: 2px 0;
        background: transparent;
        font-size: 13.5px;
        line-height: 1.54;
        color: var(--dv-text);
      }
    }
  }

  .slot-chip {
    display: inline-flex;
    align-items: center;
    vertical-align: baseline;
    height: 24px;
    padding: 0 6px;
    margin: 0 3px;
    background: var(--dv-accent-soft);
    border: 1px solid var(--dv-accent);
    border-radius: var(--dv-radius-seg-sm);
    color: var(--dv-accent-strong);
    font-weight: 600;
    font-size: 13px;

    input {
      width: 46px;
      border: none;
      outline: none;
      background: transparent;
      text-align: center;
      color: var(--dv-accent-strong);
      font-weight: 600;
      font-size: 13px;
      font-variant-numeric: tabular-nums;
    }

    &.slot-id-chip input {
      width: 88px;
    }
  }

  .slot-select {
    display: inline-block;
    vertical-align: baseline;
    height: 24px;
    margin: 0 3px;
    padding: 0 8px;
    background: var(--dv-accent-soft);
    border: 1px solid var(--dv-accent);
    border-radius: var(--dv-radius-seg-sm);
    color: var(--dv-accent-strong);
    font-weight: 600;
    font-size: 12.5px;
    cursor: pointer;
  }

  .free-edit-btn {
    margin-left: 8px;
    border: none;
    background: transparent;
    color: var(--dv-text-muted);
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.15s ease;

    &:hover:not(:disabled) {
      color: var(--dv-accent-strong);
    }

    &:disabled {
      cursor: not-allowed;
    }
  }
}

/* 框内底栏 */
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--dv-hover);
  flex-wrap: wrap;

  .composer-footer-left {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .composer-footer-right {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
  }
}

/* 路径切换胶囊 */
.seg-pill {
  display: inline-flex;
  padding: 2px;
  background: var(--dv-surface-muted);
  border-radius: var(--dv-radius-seg-sm);
  border: 1px solid var(--dv-border);

  .seg-btn {
    height: 24px;
    padding: 0 10px;
    border: none;
    border-radius: var(--dv-radius-badge);
    background: transparent;
    color: var(--dv-text-secondary);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover:not(:disabled):not(.active) {
      color: var(--dv-text);
    }

    &.active {
      background: var(--dv-surface);
      color: var(--dv-text);
      font-weight: 600;
      box-shadow: var(--dv-shadow-1);
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }
}

/* 常用查询 / 模板触发胶囊 */
.trigger-pill {
  height: 26px;
  padding: 0 10px;
  border-radius: var(--dv-radius-badge);
  border: 1px solid var(--dv-border-strong);
  background: var(--dv-surface);
  color: var(--dv-text-regular);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s ease;

  &:hover:not(:disabled) {
    background: var(--dv-hover);
    color: var(--dv-text);
  }

  &.open {
    border-color: var(--dv-accent);
    background: var(--dv-accent-soft);
    color: var(--dv-accent-strong);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .trigger-arrow {
    color: var(--dv-text-secondary);
  }

  &.open .trigger-arrow {
    color: var(--dv-accent-strong);
  }
}

.sources-summary {
  font-size: 12px;
  color: var(--dv-text-secondary);
  padding: 0 4px;
}

.quick-hint {
  font-size: 12px;
  color: var(--dv-warning);
}
</style>
