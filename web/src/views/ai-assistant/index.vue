<template>
  <div class="ai-assistant-container">
    <el-card class="chat-card">
      <template #header>
        <div class="card-header">
          <span class="title">
            <el-icon><ChatDotRound /></el-icon>
            刀小智 - 智能助手
          </span>
          <div class="header-actions">
            <el-button size="small" @click="handleReset" :loading="resetting" :disabled="compacting">
              <el-icon><RefreshRight /></el-icon>
              重置对话
            </el-button>
          </div>
        </div>
      </template>

      <div class="chat-content">
        <!-- 消息历史与流式展示列表 -->
        <ChatMessageList
          ref="chatListRef"
          :messages="messages"
          :compacted-through="contextInfo?.compaction?.through_sequence ?? null"
          :is-generating="loading"
          :has-more-history="hasMoreHistory"
          :history-loading="historyLoading"
          :actions-disabled="resetting"
          @load-earlier="loadHistory(true)"
          @retry="handleRegenerate"
          @quick-send="sendQuery"
        />

        <!-- 底部输入与路径控制区 -->
        <ChatInputArea
          v-model:route-mode="routeMode"
          :generating="loading"
          :disabled="loading || resetting || compacting"
          :context-info="contextInfo"
          @send="sendQuery"
          @compact="handleCompact"
          @sources-change="focusSources = $event"
          @abort="handleAbort"
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup name="AiAssistant">
import { nextTick, onMounted, onUnmounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { ChatDotRound, RefreshRight } from '@element-plus/icons-vue';
import { useAiAssistantApi } from '/@/api/ai-assistant';
import { ContextInfo, ContextMode, FocusSource, MemoryMetadata, Message, QuerySlot, RouteMode } from './types';
import ChatMessageList from './components/ChatMessageList.vue';
import ChatInputArea from './components/ChatInputArea.vue';
import { supportsFocusSources } from './backendCapabilities';

const api = useAiAssistantApi();

const messages = ref<Message[]>([]);
const loading = ref(false);
const resetting = ref(false);
const compacting = ref(false);
const historyLoading = ref(false);
const hasMoreHistory = ref(false);
const nextHistoryCursor = ref<number>();
const routeMode = ref<RouteMode>('rule');
// 模型路径选中的数据类型，只在模型路径发送
const focusSources = ref<FocusSource[]>([]);
const memoryInfo = ref<MemoryMetadata>();
// 上下文用量：历史接口给下一问的起步值，每轮回答给本轮的值
const contextInfo = ref<ContextInfo | null>(null);
const contextMode = ref<ContextMode>('auto');
const pendingClears = ref<QuerySlot[]>([]);
const chatListRef = ref<InstanceType<typeof ChatMessageList>>();

let abortController: AbortController | null = null;
let activePresentationCleanup: (() => void) | null = null;
let operationVersion = 0;
let messageSequence = 0;
let disposed = false;
const nextMessageId = () => `message-${++messageSequence}`;

// 单次规则回答由后端整段返回；限制展示速率可保留流式观感，
// 但首批字符立即落屏，避免旧实现固定等待造成首问卡顿。
const INITIAL_VISIBLE_CHARS = 12;

// 按时间计费的速率控制（与屏幕刷新率无关）：
// 基础约 100 字/秒保持打字感；积压越多按比例加速（约 3 秒内追平），
// 封顶 800 字/秒，保证有界逐帧消费，不允许一帧刷完全部缓冲。
const BASE_CHARS_PER_SECOND = 100;
const MAX_CHARS_PER_SECOND = 800;
const MAX_FRAME_DELTA_MS = 100;

const charsForDelta = (backlog: number, deltaMs: number) => {
  const cps = Math.min(MAX_CHARS_PER_SECOND, Math.max(BASE_CHARS_PER_SECOND, Math.round(backlog / 3)));
  return Math.max(1, Math.round((cps * deltaMs) / 1000));
};

const getCurrentTime = () => {
  const now = new Date();
  return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
};

const handleAbort = () => {
  if (abortController) {
    operationVersion += 1;
    abortController.abort();
    abortController = null;
    activePresentationCleanup?.();
    loading.value = false;
    const last = messages.value[messages.value.length - 1];
    if (last && last.role === 'assistant') {
      last.aborted = true;
    }
    ElMessage.info('已停止生成');
  }
};

// 页面刷新后从后端记忆回填历史对话；只读接口，失败时静默降级为空对话
const loadHistory = async (older = false) => {
  if (disposed || historyLoading.value || loading.value || resetting.value || compacting.value) return;
  if (older && (!hasMoreHistory.value || nextHistoryCursor.value === undefined)) return;
  const version = operationVersion;
  historyLoading.value = true;
  try {
    const response = await api.history({ limit: 50, ...(older ? { before_sequence: nextHistoryCursor.value } : {}) });
    if (disposed || version !== operationVersion) return;
    const data = response.data || {};
    nextHistoryCursor.value = typeof data.next_before_sequence === 'number' ? data.next_before_sequence : undefined;
    hasMoreHistory.value = Boolean(data.has_more && nextHistoryCursor.value !== undefined);
    if (Array.isArray(data.messages)) {
      const page = data.messages.map((item: { role: 'user' | 'assistant'; content: string; sequence?: number }) => ({
        id: item.sequence === undefined ? nextMessageId() : `history-${item.sequence}`,
        role: item.role,
        content: item.content,
        time: '',
        sequence: item.sequence,
      }));
      if (older) {
        const scrollPosition = chatListRef.value?.captureScrollPosition();
        const existingIds = new Set(messages.value.map((message) => message.id));
        messages.value = [...page.filter((message: Message) => !existingIds.has(message.id)), ...messages.value];
        await nextTick();
        if (!disposed && version === operationVersion && scrollPosition) chatListRef.value?.restoreScrollPosition(scrollPosition);
      } else {
        messages.value = page;
        chatListRef.value?.scrollToBottom(false);
      }
    }
    if (disposed || version !== operationVersion) return;
    if (!older && data.context !== undefined) contextInfo.value = data.context ?? null;
    if (!older && data.memory) {
      memoryInfo.value = {
        backend: data.memory.backend,
        message_count: data.memory.message_count,
        summary_revision: data.memory.summary_revision,
        slots: data.memory.slot_names,
        activeSlots: data.memory.active_slots,
        contextMode: data.memory.context_mode,
      };
    }
  } catch (error: any) {
    // 历史回填失败不影响正常对话
    if (older && !disposed && version === operationVersion) ElMessage.error('加载历史失败：' + (error.message || '未知错误'));
  } finally {
    if (!disposed) historyLoading.value = false;
  }
};

onMounted(() => loadHistory());

const sendQuery = (query: string) => {
  if (!query.trim() || loading.value || resetting.value || compacting.value || disposed) return;
  messages.value.push({ id: nextMessageId(), role: 'user', content: query, time: getCurrentTime() });
  runStream(query);
};

// 再问一次会创建新轮次，保留旧回答，与后端追加历史的语义一致。
const handleRegenerate = () => {
  if (loading.value || resetting.value || disposed) return;
  const lastUserMsg = [...messages.value].reverse().find((msg) => msg.role === 'user');
  if (!lastUserMsg) return;
  sendQuery(lastUserMsg.content);
};

const runStream = async (query: string) => {
  const version = ++operationVersion;
  const requestControls = {
    context_mode: contextMode.value,
    clear_slots: [...pendingClears.value],
    ...(supportsFocusSources && routeMode.value === 'agent' && focusSources.value.length ? { focus_sources: [...focusSources.value] } : {}),
  };
  loading.value = true;

  const assistantMsg: Message = { id: nextMessageId(), role: 'assistant', content: '', time: getCurrentTime(), streaming: true };
  messages.value.push(assistantMsg);
  const currentMessage = () => messages.value.find((message) => message.id === assistantMsg.id);
  let closed = false;
  const isCurrent = () => !disposed && !closed && operationVersion === version;

  chatListRef.value?.scrollToBottom();

  abortController = new AbortController();
  let pendingText = '';
  let streamFinished = false;
  let flushFrame: number | null = null;
  let hasVisibleContent = false;
  let lastFlushTime = 0;
  let hasFinalAnswer = false;
  let answerRoute = '';

  const finishIfReady = () => {
    if (!isCurrent() || !streamFinished || pendingText || flushFrame !== null) return;
    const message = currentMessage();
    if (message) message.streaming = false;
    closed = true;
    loading.value = false;
    abortController = null;
    activePresentationCleanup = null;
  };

  const appendVisibleText = (text: string) => {
    const message = currentMessage();
    if (!isCurrent() || !text || !message) return;
    message.content += text;
    hasVisibleContent = true;
    chatListRef.value?.handleSmartScroll();
  };

  const scheduleFlush = () => {
    if (isCurrent() && flushFrame === null && pendingText) {
      flushFrame = window.requestAnimationFrame(flushPending);
    }
  };

  const flushPending = (timestamp: number) => {
    flushFrame = null;
    if (!isCurrent() || !currentMessage()) {
      pendingText = '';
      return;
    }
    if (pendingText) {
      // 页签切后台等场景下帧间隔会拉长，限制单帧最大计费时长避免一次刷出过多
      const deltaMs = lastFlushTime ? Math.min(timestamp - lastFlushTime, MAX_FRAME_DELTA_MS) : 16;
      const consumeCount = charsForDelta(pendingText.length, deltaMs);
      const visibleText = pendingText.slice(0, consumeCount);
      pendingText = pendingText.slice(consumeCount);
      appendVisibleText(visibleText);
    }
    lastFlushTime = timestamp;
    scheduleFlush();
    finishIfReady();
  };

  const enqueueText = (text: string) => {
    if (!isCurrent() || !text) return;
    pendingText += text;
    if (!hasVisibleContent) {
      const firstText = pendingText.slice(0, INITIAL_VISIBLE_CHARS);
      pendingText = pendingText.slice(INITIAL_VISIBLE_CHARS);
      appendVisibleText(firstText);
    }
    scheduleFlush();
  };

  activePresentationCleanup = () => {
    pendingText = '';
    streamFinished = true;
    if (flushFrame !== null) {
      window.cancelAnimationFrame(flushFrame);
      flushFrame = null;
    }
    const message = currentMessage();
    if (message) message.streaming = false;
    closed = true;
    activePresentationCleanup = null;
  };

  await api.chatStream(
    { query, route_mode: routeMode.value, ...requestControls },
    {
      onChunk: (text) => {
        if (!hasFinalAnswer) enqueueText(text);
      },
      onAnswer: (text) => {
        if (!isCurrent()) return;
        const message = currentMessage();
        if (!message) return;
        hasFinalAnswer = true;
        if (flushFrame !== null) window.cancelAnimationFrame(flushFrame);
        flushFrame = null;
        pendingText = '';
        // 工具执行过程中的临时文本不进入最终回答；仅保留仍匹配的可见前缀。
        let prefixLength = 0;
        while (prefixLength < message.content.length && prefixLength < text.length && message.content[prefixLength] === text[prefixLength]) {
          prefixLength += 1;
        }
        message.content = message.content.slice(0, prefixLength);
        hasVisibleContent = prefixLength > 0;
        enqueueText(text.slice(message.content.length));
      },
      onMemory: ({ turnSequences, ...info }) => {
        if (!isCurrent()) return;
        memoryInfo.value = { ...memoryInfo.value, ...info };
        // 补上刚保存的问答两行序号，分隔线才能落到本次会话的消息上
        const index = messages.value.findIndex((message) => message.id === assistantMsg.id);
        const question = messages.value[index - 1];
        if (index > 0 && turnSequences?.length === 2 && question.role === 'user') {
          [question.sequence, messages.value[index].sequence] = turnSequences;
        }
      },
      onStatus: (stage) => {
        const message = currentMessage();
        if (isCurrent() && message) message.status = stage === 'compacting' || stage === 'revising' ? stage : undefined;
      },
      onMeta: (info) => {
        if (isCurrent() && info.route) answerRoute = info.route;
      },
      onContext: (info) => {
        if (isCurrent()) contextInfo.value = info as ContextInfo;
      },
      onQueryTraces: (traces) => {
        // 只有模型分析（meta route=llm）的回答显示"本次查询"，规则直答不显示
        const message = currentMessage();
        if (isCurrent() && message && answerRoute === 'llm') message.queryTraces = traces;
      },
      onDone: () => {
        if (!isCurrent()) return;
        pendingClears.value = [];
        contextMode.value = 'auto';
        streamFinished = true;
        finishIfReady();
      },
      onError: (msg) => {
        if (!isCurrent()) return;
        const message = currentMessage();
        if (!message) return;
        if (flushFrame !== null) {
          window.cancelAnimationFrame(flushFrame);
          flushFrame = null;
        }
        if (pendingText) {
          message.content += pendingText;
          pendingText = '';
        }
        const prefix = message.content ? '\n\n' : '';
        message.content += `${prefix}抱歉，出错了：${msg}`;
        message.rawError = true;
        streamFinished = true;
        finishIfReady();
      },
    },
    abortController.signal
  );
};

// 手动把早前对话整理成摘要；只在后端声明支持（compaction.manual）时显示按钮
const handleCompact = async () => {
  if (compacting.value || loading.value || resetting.value || disposed) return;
  const version = operationVersion;
  compacting.value = true;
  try {
    const response = await api.compact();
    if (disposed || version !== operationVersion) return;
    if (response.data?.context) contextInfo.value = response.data.context;
    ElMessage.success('已整理早前对话');
  } catch (error: any) {
    if (!disposed && version === operationVersion) ElMessage.error('整理失败：' + (error.message || '未知错误'));
  } finally {
    if (!disposed) compacting.value = false;
  }
};

const handleReset = async () => {
  if (resetting.value || compacting.value || disposed) return;
  const version = ++operationVersion;
  try {
    resetting.value = true;
    const last = messages.value[messages.value.length - 1];
    if (last?.streaming) last.aborted = true;
    abortController?.abort();
    abortController = null;
    activePresentationCleanup?.();
    loading.value = false;
    const response = await api.reset();
    if (disposed || version !== operationVersion) return;
    messages.value = [];
    memoryInfo.value = undefined;
    contextInfo.value = null;
    contextMode.value = 'auto';
    pendingClears.value = [];
    hasMoreHistory.value = false;
    nextHistoryCursor.value = undefined;
    ElMessage.success(response.data?.message || '对话已重置');
  } catch (error: any) {
    if (!disposed && version === operationVersion) ElMessage.error('重置失败：' + (error.message || '未知错误'));
  } finally {
    if (!disposed && version === operationVersion) resetting.value = false;
  }
};

onUnmounted(() => {
  disposed = true;
  operationVersion += 1;
  abortController?.abort();
  activePresentationCleanup?.();
});
</script>

<style scoped lang="scss">
.ai-assistant-container {
  // 布局给出的路由页面可用高度（顶栏、页脚以外），刚好填满到页脚上沿
  height: var(--dv-main-height);
  padding: 10px 12px 8px;

  .chat-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__header) {
      padding: 14px 20px;
      border-bottom: 1px solid #ebeef5;
    }

    :deep(.el-card__body) {
      flex: 1;
      padding: 0;
      overflow: hidden;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      .title {
        font-size: 16px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 8px;
        color: #1e293b;
      }
    }

    .chat-content {
      height: 100%;
      display: flex;
      flex-direction: column;
    }
  }
}
</style>
