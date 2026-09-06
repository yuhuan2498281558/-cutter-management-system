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
            <el-button size="small" @click="handleReset" :loading="resetting">
              <el-icon><RefreshRight /></el-icon>
              重置对话
            </el-button>
          </div>
        </div>
      </template>

      <div class="chat-content">
        <!-- 记忆槽位状态栏 -->
        <MemorySlotBadge :memory-info="memoryInfo" />

        <!-- 消息历史与流式展示列表 -->
        <ChatMessageList
          ref="chatListRef"
          :messages="messages"
          :is-generating="loading"
          @retry="handleRegenerate"
          @quick-send="sendQuery"
        />

        <!-- 底部输入与路径控制区 -->
        <ChatInputArea
          v-model:route-mode="routeMode"
          :loading="loading"
          @send="sendQuery"
          @abort="handleAbort"
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup name="AiAssistant">
import { onMounted, onUnmounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { ChatDotRound, RefreshRight } from '@element-plus/icons-vue';
import { useAiAssistantApi } from '/@/api/ai-assistant';
import { MemoryMetadata, Message, RouteMode } from './types';
import ChatMessageList from './components/ChatMessageList.vue';
import ChatInputArea from './components/ChatInputArea.vue';
import MemorySlotBadge from './components/MemorySlotBadge.vue';

const api = useAiAssistantApi();

const messages = ref<Message[]>([]);
const loading = ref(false);
const resetting = ref(false);
const routeMode = ref<RouteMode>('rule');
const memoryInfo = ref<MemoryMetadata>();
const chatListRef = ref<InstanceType<typeof ChatMessageList>>();

let abortController: AbortController | null = null;
let activePresentationCleanup: (() => void) | null = null;

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
const loadHistory = async () => {
  try {
    const response = await api.history();
    const data = response.data || {};
    if (Array.isArray(data.messages) && data.messages.length) {
      messages.value = data.messages.map((item: { role: 'user' | 'assistant'; content: string }) => ({
        role: item.role,
        content: item.content,
        time: '',
      }));
      chatListRef.value?.scrollToBottom(false);
    }
    if (data.memory) {
      memoryInfo.value = {
        backend: data.memory.backend,
        message_count: data.memory.message_count,
        summary_revision: data.memory.summary_revision,
        slots: data.memory.slot_names,
      };
    }
  } catch {
    // 历史回填失败不影响正常对话
  }
};

onMounted(loadHistory);

const sendQuery = (query: string) => {
  if (!query.trim() || loading.value) return;
  messages.value.push({ role: 'user', content: query, time: getCurrentTime() });
  runStream(query);
};

// 重新生成：复用最后一个用户问题，替换最后一条助手回答，不重复追加用户消息
const handleRegenerate = () => {
  if (loading.value) return;
  const lastUserMsg = [...messages.value].reverse().find((msg) => msg.role === 'user');
  if (!lastUserMsg) return;
  const last = messages.value[messages.value.length - 1];
  if (last && last.role === 'assistant') {
    messages.value.pop();
  }
  runStream(lastUserMsg.content);
};

const runStream = async (query: string) => {
  loading.value = true;

  const assistantMsg: Message = { role: 'assistant', content: '', time: getCurrentTime(), streaming: true };
  messages.value.push(assistantMsg);
  const msgIndex = messages.value.length - 1;

  chatListRef.value?.scrollToBottom();

  abortController = new AbortController();
  let pendingText = '';
  let streamFinished = false;
  let flushFrame: number | null = null;
  let hasVisibleContent = false;
  let lastFlushTime = 0;

  const finishIfReady = () => {
    if (!streamFinished || pendingText || flushFrame !== null) return;
    if (messages.value[msgIndex]) messages.value[msgIndex].streaming = false;
    loading.value = false;
    abortController = null;
    activePresentationCleanup = null;
  };

  const appendVisibleText = (text: string) => {
    if (!text || !messages.value[msgIndex]) return;
    messages.value[msgIndex].content += text;
    hasVisibleContent = true;
    chatListRef.value?.handleSmartScroll();
  };

  const scheduleFlush = () => {
    if (flushFrame === null && pendingText) {
      flushFrame = window.requestAnimationFrame(flushPending);
    }
  };

  const flushPending = (timestamp: number) => {
    flushFrame = null;
    if (!messages.value[msgIndex]) {
      pendingText = '';
      loading.value = false;
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
    if (!text) return;
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
    if (messages.value[msgIndex]) messages.value[msgIndex].streaming = false;
    activePresentationCleanup = null;
  };

  await api.chatStream(
    { query, route_mode: routeMode.value },
    {
      onChunk: (text) => {
        enqueueText(text);
      },
      onMemory: (info) => {
        memoryInfo.value = { ...memoryInfo.value, ...info };
      },
      onDone: () => {
        streamFinished = true;
        finishIfReady();
      },
      onError: (msg) => {
        if (flushFrame !== null) {
          window.cancelAnimationFrame(flushFrame);
          flushFrame = null;
        }
        if (pendingText) {
          messages.value[msgIndex].content += pendingText;
          pendingText = '';
        }
        const prefix = messages.value[msgIndex].content ? '\n\n' : '';
        messages.value[msgIndex].content += `${prefix}抱歉，出错了：${msg}`;
        messages.value[msgIndex].rawError = true;
        streamFinished = true;
        finishIfReady();
      },
    },
    abortController.signal
  );
};

const handleReset = async () => {
  try {
    resetting.value = true;
    abortController?.abort();
    abortController = null;
    activePresentationCleanup?.();
    loading.value = false;
    const response = await api.reset();
    messages.value = [];
    memoryInfo.value = undefined;
    ElMessage.success(response.data?.message || '对话已重置');
  } catch (error: any) {
    ElMessage.error('重置失败：' + (error.message || '未知错误'));
  } finally {
    resetting.value = false;
  }
};

onUnmounted(() => {
  abortController?.abort();
  activePresentationCleanup?.();
});
</script>

<style scoped lang="scss">
.ai-assistant-container {
  // 113px = 顶部导航 + 标签栏实测高度，刚好填满到页脚上沿
  height: calc(100vh - 113px);
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
