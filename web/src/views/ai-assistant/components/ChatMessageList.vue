<template>
  <div class="chat-message-list-wrapper">
    <div class="messages-container" ref="containerRef" @scroll="handleScroll">
      <div class="messages-inner">
      <div v-if="hasMoreHistory" class="history-actions">
        <el-button size="small" :loading="historyLoading" :disabled="isGenerating || actionsDisabled" @click="$emit('load-earlier')">
          加载更早消息
        </el-button>
      </div>
      <div v-if="messages.length === 0" class="welcome-message">
        <div class="welcome-icon">
          <el-icon :size="30"><ChatDotRound /></el-icon>
        </div>
        <h3>你好，我是刀小智</h3>
        <p>点击常用问题直接提问，或在下方输入框描述你的需求。</p>
        <div class="welcome-chips">
          <button
            v-for="chip in welcomeChips"
            :key="chip.label"
            type="button"
            class="welcome-chip"
            :title="chip.query"
            @click="$emit('quick-send', chip.query)"
          >
            {{ chip.label }}
          </button>
        </div>
      </div>

      <div
        v-for="(msg, index) in messages"
        :key="msg.id"
        :class="['message-item', msg.role]"
      >
        <div class="message-avatar">
          <el-icon v-if="msg.role === 'user'" :size="18"><User /></el-icon>
          <el-icon v-else :size="18"><ChatDotRound /></el-icon>
        </div>
        <div class="message-content">
          <div v-if="msg.content" :class="['message-text', { error: msg.rawError }]">
            <AnalysisMessage
              v-if="msg.role === 'assistant'"
              :content="msg.content"
            />
            <template v-else>{{ msg.content }}</template>
          </div>
          <div v-else-if="msg.streaming" class="message-text typing">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <div class="message-meta">
            <span v-if="msg.streaming" class="message-time generating">正在生成 · {{ elapsedSec }}s</span>
            <span v-else-if="msg.time" class="message-time">{{ msg.time }}</span>
            <span v-if="msg.aborted" class="aborted-tag">已停止，回答不完整</span>
            <button
              v-if="msg.content && !msg.streaming"
              type="button"
              class="meta-btn"
              title="复制内容"
              @click="handleCopy(msg.content)"
            >
              <el-icon :size="12"><DocumentCopy /></el-icon>
              复制
            </button>
            <button
              v-if="canRetry(msg, index)"
              type="button"
              class="meta-btn"
              title="用上一个问题开始新一轮，保留原有回答"
              @click="$emit('retry')"
            >
              <el-icon :size="12"><RefreshRight /></el-icon>
              再问一次
            </button>
          </div>
        </div>
      </div>
      </div>
    </div>

    <!-- 不在底部时的回到底部悬浮按钮 -->
    <transition name="fade">
      <button
        v-if="!isNearBottom && messages.length > 0"
        type="button"
        class="scroll-bottom-badge"
        @click="scrollToBottom"
      >
        <el-icon><ArrowDown /></el-icon>
        {{ isGenerating ? '有新内容生成' : '回到底部' }}
      </button>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { ChatDotRound, User, DocumentCopy, ArrowDown, RefreshRight } from '@element-plus/icons-vue';
import { Message } from '../types';
import { quickQuestionGroups } from '../constants';
import AnalysisMessage from './AnalysisMessage.vue';

const props = defineProps<{
  messages: Message[];
  isGenerating?: boolean;
  hasMoreHistory?: boolean;
  historyLoading?: boolean;
  actionsDisabled?: boolean;
}>();

defineEmits<{
  (e: 'retry'): void;
  (e: 'quick-send', query: string): void;
  (e: 'load-earlier'): void;
}>();

// 欢迎区快捷问题：直接复用快捷问题库中已验证的原句，不新增问法
const WELCOME_REFS: Array<[string, string]> = [
  ['换刀/旧刀补录', '换刀汇总'],
  ['换刀/旧刀补录', '异常磨损'],
  ['刀位统计', '高频刀位'],
  ['开仓记录', '开仓间隔'],
  ['地层信息', '地层分布'],
  ['寿命预测', '寿命概况'],
];

const welcomeChips = WELCOME_REFS
  .map(([group, label]) => {
    const item = quickQuestionGroups
      .find((g) => g.title === group)
      ?.items.find((i) => i.label === label);
    return item ? { label: item.label, query: item.query } : null;
  })
  .filter((item): item is { label: string; query: string } => item !== null);

const containerRef = ref<HTMLElement>();
const isNearBottom = ref(true);

// 生成用时计时器：模型路径可能耗时较久，给用户"仍在正常工作"的反馈
const elapsedSec = ref(0);
let elapsedTimer: number | null = null;

watch(
  () => props.isGenerating,
  (generating) => {
    if (generating) {
      elapsedSec.value = 0;
      const startedAt = Date.now();
      elapsedTimer = window.setInterval(() => {
        elapsedSec.value = Math.floor((Date.now() - startedAt) / 1000);
      }, 1000);
    } else if (elapsedTimer !== null) {
      window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }
);

onUnmounted(() => {
  if (elapsedTimer !== null) {
    window.clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
});

const canRetry = (msg: Message, index: number) => {
  return (
    msg.role === 'assistant'
    && !msg.streaming
    && !props.isGenerating
    && !props.actionsDisabled
    && !!msg.content
    && index === props.messages.length - 1
  );
};

const handleScroll = () => {
  if (!containerRef.value) return;
  const { scrollTop, scrollHeight, clientHeight } = containerRef.value;
  // 距离底部 60px 以内判定为处于底部
  isNearBottom.value = scrollHeight - (scrollTop + clientHeight) < 60;
};

const scrollToBottom = (smooth = true) => {
  nextTick(() => {
    if (!containerRef.value) return;
    containerRef.value.scrollTo({
      top: containerRef.value.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
    isNearBottom.value = true;
  });
};

const handleSmartScroll = () => {
  if (isNearBottom.value) {
    scrollToBottom(false);
  }
};

const captureScrollPosition = () => {
  if (!containerRef.value) return undefined;
  return { top: containerRef.value.scrollTop, height: containerRef.value.scrollHeight };
};

const restoreScrollPosition = (position: { top: number; height: number }) => {
  if (!containerRef.value) return;
  containerRef.value.scrollTop = position.top + containerRef.value.scrollHeight - position.height;
  handleScroll();
};

const handleCopy = async (text: string) => {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    ElMessage.success('已复制到剪贴板');
  } catch {
    ElMessage.error('复制失败，请手动选择复制');
  }
};

defineExpose({
  scrollToBottom,
  handleSmartScroll,
  captureScrollPosition,
  restoreScrollPosition,
});
</script>

<style scoped lang="scss">
.history-actions {
  padding: 0 0 12px;
  text-align: center;
}

.chat-message-list-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  background: #f7f9fc;
}

// 宽屏下限制内容列宽，保持行长可读
.messages-inner {
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.welcome-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 36px 16px 24px;
  color: #64748b;
  text-align: center;

  .welcome-icon {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #ecf5ff;
    color: #409eff;
  }

  h3 {
    margin: 14px 0 6px;
    font-size: 17px;
    color: #1e293b;
  }

  p {
    margin: 0 0 16px;
    font-size: 13px;
  }

  .welcome-chips {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    max-width: 560px;
  }

  .welcome-chip {
    padding: 6px 14px;
    border: 1px solid #d9e2ec;
    border-radius: 15px;
    background: #fff;
    font-size: 13px;
    color: #475569;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover {
      border-color: #409eff;
      color: #409eff;
      background: #f5f9ff;
    }
  }
}

.message-item {
  display: flex;
  gap: 10px;
  max-width: 92%;

  .message-avatar {
    flex-shrink: 0;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e2e8f0;
    color: #64748b;
  }

  .message-content {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;

    .message-text {
      padding: 10px 14px;
      border-radius: 10px;
      font-size: 14px;
      line-height: 1.6;
      word-break: break-word;
    }

    .message-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 0 4px;
    }

    .message-time {
      font-size: 11px;
      color: #94a3b8;

      &.generating {
        color: #409eff;
      }
    }

    .aborted-tag {
      font-size: 11px;
      color: #e6a23c;
    }

    .meta-btn {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      border: none;
      background: none;
      font-size: 11px;
      color: #94a3b8;
      cursor: pointer;
      padding: 1px 4px;
      border-radius: 3px;
      transition: all 0.15s ease;

      &:hover {
        color: #409eff;
        background: #ecf5ff;
      }
    }
  }

  &.user {
    align-self: flex-end;
    flex-direction: row-reverse;

    .message-avatar {
      background: #409eff;
      color: #fff;
    }

    .message-text {
      background: #409eff;
      color: #fff;
      border-radius: 10px 2px 10px 10px;
      white-space: pre-wrap;
    }

    .message-meta {
      justify-content: flex-end;
    }
  }

  &.assistant {
    align-self: flex-start;
    // 助手消息占满内容列，分析卡片和表格不再缩在左侧
    width: 92%;

    .message-content {
      flex: 1;

      // 打字指示气泡保持紧凑，不随内容列拉伸
      .message-text.typing {
        align-self: flex-start;
      }
    }

    .message-avatar {
      background: #e1f3d8;
      color: #67c23a;
    }

    .message-text {
      background: #fff;
      border: 1px solid #e5e9f0;
      border-radius: 2px 10px 10px 10px;
      color: #303133;

      &.error {
        background: #fef0f0;
        border-color: #fab6b6;
        color: #c45656;
      }

      &.typing {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 12px 16px;

        span {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #909399;
          animation: typing 1.2s infinite ease-in-out;

          &:nth-child(1) { animation-delay: 0s; }
          &:nth-child(2) { animation-delay: 0.2s; }
          &:nth-child(3) { animation-delay: 0.4s; }
        }
      }
    }
  }
}

.scroll-bottom-badge {
  position: absolute;
  bottom: 12px;
  right: 24px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: #409eff;
  color: #fff;
  border: none;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.4);
  transition: all 0.2s ease;

  &:hover {
    background: #66b1ff;
    transform: translateY(-1px);
  }
}

@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
