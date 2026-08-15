<template>
  <div class="ai-assistant-container">
    <el-card class="chat-card">
      <template #header>
        <div class="card-header">
          <span class="title">
            <el-icon><ChatDotRound /></el-icon>
            刀小智 - 智能助手
          </span>
          <el-button size="small" @click="handleReset" :loading="resetting">
            <el-icon><RefreshRight /></el-icon>
            重置对话
          </el-button>
        </div>
      </template>

      <div class="chat-content">
        <div class="messages-container" ref="messagesContainer">
          <div v-if="messages.length === 0" class="welcome-message compact">
            <el-icon :size="40" color="#409EFF"><ChatDotRound /></el-icon>
            <h3>你好，我是刀小智</h3>
            <p>先选择数据类型快速查询；需要原因分析时再走模型路径。</p>
          </div>

          <div
            v-for="(msg, index) in messages"
            :key="index"
            :class="['message-item', msg.role]"
          >
            <div class="message-avatar">
              <el-icon v-if="msg.role === 'user'" :size="24"><User /></el-icon>
              <el-icon v-else :size="24"><ChatDotRound /></el-icon>
            </div>
            <div class="message-content">
              <div v-if="msg.content" class="message-text">
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
              <div class="message-time">{{ msg.time }}</div>
            </div>
          </div>
        </div>

        <div class="input-container">
          <div class="route-switch">
            <button
              :class="['route-option', { active: routeMode === 'rule' }]"
              :disabled="loading"
              @click="switchRouteMode('rule')"
            >
              规则路径
              <span>快速查询</span>
            </button>
            <button
              :class="['route-option', { active: routeMode === 'agent' }]"
              :disabled="loading"
              @click="switchRouteMode('agent')"
            >
              模型路径
              <span>复杂分析</span>
            </button>
          </div>

          <div class="prompt-dock" :class="{ model: routeMode === 'agent' }">
            <span class="dock-label">{{ routeMode === 'rule' ? '快捷问题' : '分析助手' }}</span>
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
              <el-button class="quick-run" type="primary" size="small" :disabled="loading" @click="handleUseQuickQuestion">生成问题</el-button>
            </template>

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
                @change="handleModelPromptChange"
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
            v-model="inputText"
            type="textarea"
            :rows="2"
            :placeholder="routeMode === 'rule' ? '输入规则查询，例如：统计最近100环的换刀情况' : '输入复杂分析问题，可结合多个数据类型追问原因和建议'"
            @keydown.enter.ctrl="handleSend"
            :disabled="loading"
          />
          <div class="input-actions">
            <span class="input-tip">{{ routeMode === 'rule' ? '规则路径：下拉选择后可直接生成问题' : '模型路径：选择数据能力与分析模板后自动填入' }} · Ctrl + Enter 发送</span>
            <el-button type="primary" @click="handleSend" :loading="loading">发送</el-button>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script lang="ts" setup name="AiAssistant">
import { computed, defineComponent, h, ref, nextTick, onMounted, onUnmounted } from 'vue';
import { ElMessage } from 'element-plus';
import { ChatDotRound, User, RefreshRight } from '@element-plus/icons-vue';
import { useAiAssistantApi } from '/@/api/ai-assistant';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  time: string;
  streaming?: boolean;
}

interface AnalysisSection {
  title: string;
  kind: 'conclusion' | 'evidence' | 'warning' | 'suggestion' | 'default';
  items: string[];
}

const SECTION_TITLES = [
  '结论',
  '关键依据',
  '数据依据',
  '关键发现',
  '注意事项',
  '注意事项/建议',
  '建议',
];

const normalizeTitle = (title: string) => title.replace(/[：:]\s*$/, '').trim();

const sectionKind = (title: string): AnalysisSection['kind'] => {
  if (title.includes('结论')) return 'conclusion';
  if (title.includes('依据') || title.includes('发现')) return 'evidence';
  if (title.includes('注意')) return 'warning';
  if (title.includes('建议')) return 'suggestion';
  return 'default';
};

const splitItems = (text: string) => {
  return text
    .split('\n')
    .map((line) => line.trim().replace(/^[-•]\s*/, ''))
    .filter(Boolean);
};

const parseAnalysisMessage = (content: string) => {
  const lines = content.split('\n');
  const sections: AnalysisSection[] = [];
  let lead: string[] = [];
  let current: AnalysisSection | null = null;

  const pushCurrent = () => {
    if (current && current.items.length) sections.push(current);
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;

    const inlineTitle = SECTION_TITLES.find((title) => line.startsWith(`${title}：`) || line.startsWith(`${title}:`));
    if (inlineTitle) {
      pushCurrent();
      const rest = line.slice(inlineTitle.length + 1).trim();
      current = {
        title: inlineTitle,
        kind: sectionKind(inlineTitle),
        items: rest ? [rest] : [],
      };
      continue;
    }

    const pureTitle = SECTION_TITLES.find((title) => normalizeTitle(line) === title);
    if (pureTitle) {
      pushCurrent();
      current = { title: pureTitle, kind: sectionKind(pureTitle), items: [] };
      continue;
    }

    if (current) current.items.push(line.replace(/^[-•]\s*/, ''));
    else lead.push(line);
  }

  pushCurrent();

  return {
    lead: lead.join('\n'),
    sections,
  };
};

const AnalysisMessage = defineComponent({
  name: 'AnalysisMessage',
  props: {
    content: {
      type: String,
      required: true,
    },
  },
  setup(props) {
    const parsed = computed(() => parseAnalysisMessage(props.content));
    return () => {
      if (!parsed.value.sections.length) {
        return h('div', { class: 'plain-answer' }, props.content);
      }

      return h('div', { class: 'analysis-answer' }, [
        parsed.value.lead
          ? h('p', { class: 'analysis-lead' }, parsed.value.lead)
          : null,
        ...parsed.value.sections.map((section) =>
          h('div', { class: ['analysis-section', section.kind] }, [
            h('div', { class: 'analysis-section-title' }, section.title),
            section.items.length > 1
              ? h('ul', section.items.map((item) => h('li', item)))
              : h('p', splitItems(section.items[0] || '').join('\n')),
          ])
        ),
      ]);
    };
  },
});

const api = useAiAssistantApi();

const messages = ref<Message[]>([]);
const inputText = ref('');
const selectedModelDataTypes = ref<string[]>(['换刀明细', '地层信息']);
const selectedModelPrompt = ref('');
const routeMode = ref<'rule' | 'agent'>('rule');
interface QuickQuestionItem {
  label: string;
  query: string;
  numKey?: 'openingLimit' | 'ringWindow' | 'topN' | 'interval';
  min?: number;
  max?: number;
  step?: number;
}


const modelDataTypes = [
  '换刀/旧刀补录', '开仓记录', '刀位统计', '地层信息', '掘进参数', '厂家表现', '寿命预警', '备刀建议', '趋势分析', '跨源联动',
];
const modelPromptLibrary: Record<string, string[]> = {
  '换刀/旧刀补录': [
    '分析近期换刀异常是否集中在特定磨损类型、刀具类型或刀位区域，并给出原因判断',
    '结合换刀明细识别异常磨损的主要模式、集中环段和需要复核的作业环节',
  ],
  开仓记录: [
    '结合最近开仓记录分析异常率较高开仓的共同特征，以及与换刀工作量的关系',
    '分析开仓间隔、开仓时长、检查数量和更换数量之间是否存在异常联动',
  ],
  刀位统计: [
    '分析高频刀位是否呈现局部集中、相邻刀位联动或刀盘区域性磨损风险',
    '结合刀位统计识别需要优先复核的刀位组合，并解释可能的受力或安装原因',
  ],
  地层信息: [
    '分析地层变化是否可能解释近期异常磨损，并指出对应磨损类型和高风险刀位',
    '结合地层分布判断不同地层对换刀频率、异常率和刀位风险的影响',
  ],
  掘进参数: [
    '分析掘进参数波动是否与异常磨损、换刀频率上升或刀位集中损伤有关',
    '结合推力、扭矩、转速和贯入力变化，判断近期刀具磨损风险的可能工况原因',
  ],
  厂家表现: [
    '结合厂家表现、地层条件和刀具类型，分析异常磨损差异是否具有稳定性',
    '评估近期厂家刀具表现差异，并给出后续选型和复核建议',
  ],
  寿命预警: [
    '结合平均寿命、累计推进和高频刀位，判断近期是否存在集中到寿风险',
    '分析寿命预警刀位与近期异常磨损、地层变化和开仓记录之间的关系',
  ],
  备刀建议: [
    '结合近期消耗、异常磨损、地层变化和厂家表现，形成下一阶段备刀策略',
    '基于高风险刀位、失效模式和厂家表现，给出备刀优先级和关注原因',
  ],
  趋势分析: [
    '分析近期换刀趋势是否出现阶段性抬升，并解释可能的地层、刀位或工况原因',
    '对比前后阶段换刀频率、异常磨损和高频刀位变化，判断风险是否加剧',
  ],
  跨源联动: [
    '结合最近开仓、地层和换刀数据，分析哪些开仓异常率高以及对应地层和高频刀位',
    '结合地层、掘进参数和换刀记录，分析近期异常磨损的可能原因',
    '综合换刀、开仓、地层、刀位、厂家和寿命数据，生成近期风险清单和处理建议',
  ],
};

const defaultModelPrompts = [
  '结合地层、掘进参数和换刀记录，分析近期异常磨损的可能原因',
  '结合最近开仓、地层和换刀数据，分析哪些开仓异常率高以及对应地层和高频刀位',
  '综合换刀、开仓、地层、刀位、厂家和寿命数据，生成近期风险清单和处理建议',
];

const modelPromptOptions = computed(() => {
  const prompts = selectedModelDataTypes.value.flatMap((type) => modelPromptLibrary[type] || []);
  return Array.from(new Set(prompts.length ? prompts : defaultModelPrompts));
});
const quickParams = ref({
  openingLimit: 5,
  ringWindow: 100,
  topN: 10,
  interval: 50,
});

const quickQuestionGroups: Array<{ title: string; desc: string; items: QuickQuestionItem[] }> = [
  {
    title: '换刀/旧刀补录',
    desc: '检查数、更换数、旧刀补录磨损类型和高频刀位',
    items: [
      { label: '近{n}环统计', query: '统计最近{n}环的换刀情况，列出检查数、更换数、更换率、主要磨损类型和高频刀位', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '换刀汇总', query: '统计当前项目换刀情况，列出检查数、更换数、更换率和主要磨损类型' },
      { label: '异常磨损', query: '统计异常磨损记录，列出异常类型、数量和占比' },
      { label: '更换率', query: '统计换刀更换率，并列出主要更换刀位' },
      { label: '滚刀统计', query: '统计滚刀换刀情况，列出检查数、更换数和主要磨损类型' },
      { label: '刮刀统计', query: '统计刮刀换刀情况，列出检查数、更换数和主要磨损类型' },
    ],
  },
  {
    title: '趋势区间',
    desc: '按环段观察换刀频率和异常变化',
    items: [
      { label: '{n}环分段', query: '按{n}环为一段统计换刀趋势，列出每段检查数、更换数和更换率', numKey: 'interval', min: 10, max: 200, step: 10 },
      { label: '近{n}环趋势', query: '分析最近{n}环换刀趋势，说明更换率是否上升', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '阶段对比', query: '对比前后阶段换刀频率和异常磨损变化' },
      { label: '峰值环段', query: '找出换刀频率最高的环段并列出主要刀位' },
      { label: '100-300环', query: '统计100环到300环的换刀趋势和主要磨损类型' },
    ],
  },
  {
    title: '开仓记录',
    desc: '开仓间隔、时长、异常率和换刀数量',
    items: [
      { label: '近{n}次开仓', query: '查询最近{n}次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率', numKey: 'openingLimit', min: 1, max: 20 },
      { label: '开仓异常', query: '分析最近开仓记录中异常磨损率较高的开仓' },
      { label: '开仓效率', query: '结合开仓时长和检查刀具数量，统计平均检查一把刀需要多长时间' },
      { label: '更换效率', query: '结合开仓时长和更换刀具数量，统计平均更换一把刀需要多长时间' },
      { label: '开仓间隔', query: '统计平均多少环开一次仓，并列出最近开仓间隔' },
    ],
  },
  {
    title: '刀位统计',
    desc: '定位高频更换和高风险刀位',
    items: [
      { label: '前{n}刀位', query: '列出更换次数最高的前{n}个刀位，并说明刀具类型和主要磨损类型', numKey: 'topN', min: 3, max: 30 },
      { label: '高频刀位', query: '分析高频更换刀位，列出更换次数和主要磨损类型' },
      { label: '异常刀位', query: '找出异常磨损集中的刀位，并列出异常类型' },
      { label: '刀盘分布', query: '分析刀盘不同刀位的磨损分布情况' },
      { label: '指定刀位', query: '分析G3R刀位的换刀和磨损情况' },
    ],
  },
  {
    title: '地层信息',
    desc: '地层分布和地层-磨损关联',
    items: [
      { label: '地层分布', query: '统计当前项目地层分布，列出各地层类型占比' },
      { label: '区间地层', query: '查询100环到300环的地层分布情况' },
      { label: '地层磨损', query: '分析地层类型与刀具磨损的关联' },
      { label: '地层换刀', query: '分析不同地层下的换刀数量和更换率' },
      { label: '刀位地层', query: '分析刀位受地层影响的情况，列出高风险刀位' },
    ],
  },
  {
    title: '掘进动态',
    desc: '推力、扭矩、转速、贯入力趋势',
    items: [
      { label: '参数概览', query: '查询近期掘进动态参数概览，列出推力、扭矩、转速和贯入力' },
      { label: '异常检查', query: '检查近期掘进参数异常，列出偏高或波动明显的环段' },
      { label: '近{n}环参数', query: '分析最近{n}环掘进参数趋势', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '参数磨损', query: '分析掘进参数与换刀磨损的关联' },
      { label: '波动原因', query: '结合掘进参数和换刀记录，分析异常磨损可能原因' },
    ],
  },
  {
    title: '厂家刀具',
    desc: '厂家表现、异常率和成本线索',
    items: [
      { label: '厂家对比', query: '对比不同厂家刀具表现，列出更换数、异常磨损率和主要磨损类型' },
      { label: '滚刀厂家', query: '对比滚刀不同厂家的更换率和异常磨损率' },
      { label: '刮刀厂家', query: '对比刮刀不同厂家的更换率和异常磨损率' },
      { label: '厂家地层', query: '分析厂家表现与地层类型的关联' },
      { label: '稳定厂家', query: '找出异常磨损率较低、表现相对稳定的厂家' },
    ],
  },
  {
    title: '寿命预警',
    desc: '平均寿命、累计推进和风险提示',
    items: [
      { label: '寿命概览', query: '统计刀具平均寿命和高风险刀位，给出寿命预警' },
      { label: '接近寿命', query: '找出累计推进接近平均寿命的刀位' },
      { label: '超寿命', query: '找出累计推进超过平均寿命的刀位，并按风险排序' },
      { label: '性能统计', query: '统计刀具性能，列出平均更换间隔和更换次数' },
      { label: '刀位寿命', query: '分析高频刀位的平均寿命和当前风险' },
    ],
  },
  {
    title: '综合联动',
    desc: '开仓、地层、刀位和掘进参数交叉分析',
    items: [
      { label: '开仓-地层-刀位', query: '结合最近开仓、地层和换刀数据，分析哪些开仓异常率高以及对应地层和高频刀位' },
      { label: '地层-掘进-换刀', query: '结合地层、掘进参数和换刀记录，分析近期异常磨损的可能原因' },
      { label: '近{n}环联动', query: '结合最近{n}环地层、掘进参数和换刀记录，分析异常磨损风险', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '异常归因', query: '结合开仓异常率、主要磨损类型和高频刀位，分析异常磨损可能原因' },
      { label: '风险清单', query: '生成近期需要重点关注的开仓、刀位、地层和掘进参数风险清单' },
    ],
  },
  {
    title: '备刀建议',
    desc: '基于近期消耗和工况生成备刀方向',
    items: [
      { label: '备刀清单', query: '基于当前换刀、刀位、地层和厂家数据，给出下一阶段备刀建议' },
      { label: '高风险备刀', query: '根据高频更换刀位和异常磨损类型，给出重点备刀建议' },
      { label: '厂家备选', query: '结合厂家表现和近期换刀情况，给出备刀厂家选择建议' },
      { label: '地层备刀', query: '结合近期地层变化和历史换刀情况，给出备刀建议' },
      { label: '库存优先级', query: '根据更换频率、异常率和刀位风险，生成备刀优先级' },
    ],
  },
];
const activeQuickGroup = ref(quickQuestionGroups[0].title);
const activeQuickItemLabel = ref(quickQuestionGroups[0].items[0].label);
const selectedQuickGroup = computed(() => quickQuestionGroups.find((group) => group.title === activeQuickGroup.value) || quickQuestionGroups[0]);
const selectedQuickItem = computed(() => selectedQuickGroup.value.items.find((item) => item.label === activeQuickItemLabel.value) || selectedQuickGroup.value.items[0]);

const handleQuickGroupChange = () => {
  activeQuickItemLabel.value = selectedQuickGroup.value.items[0]?.label || '';
};

const getQuickNumber = (item: QuickQuestionItem) => item.numKey ? quickParams.value[item.numKey] : undefined;

const buildQuickLabel = (item: QuickQuestionItem) => {
  const num = getQuickNumber(item);
  return num === undefined ? item.label : item.label.replace('{n}', String(num));
};

const buildQuickQuery = (item: QuickQuestionItem) => {
  const num = getQuickNumber(item);
  return num === undefined ? item.query : item.query.replaceAll('{n}', String(num));
};
const loading = ref(false);
const resetting = ref(false);
const messagesContainer = ref<HTMLElement>();

let abortController: AbortController | null = null;

const getCurrentTime = () => {
  const now = new Date();
  return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
};

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
    }
  });
};

const switchRouteMode = (mode: 'rule' | 'agent') => {
  routeMode.value = mode;
  if (mode === 'agent') {
    if (!selectedModelPrompt.value) selectedModelPrompt.value = modelPromptOptions.value[0] || '';
    composeModelQuestion();
  }
};
const sendQuery = async (query: string) => {
  if (!query.trim() || loading.value) return;

  messages.value.push({ role: 'user', content: query, time: getCurrentTime() });
  inputText.value = '';
  loading.value = true;

  const assistantMsg: Message = { role: 'assistant', content: '', time: getCurrentTime(), streaming: true };
  messages.value.push(assistantMsg);
  const msgIndex = messages.value.length - 1;

  abortController = new AbortController();
  let pendingText = '';
  let streamFinished = false;
  let typingTimer: ReturnType<typeof window.setTimeout> | null = null;

  const finishIfReady = () => {
    if (!streamFinished || pendingText || typingTimer) return;
    // 重置对话会清空 messages，此时该条已不存在，直接收尾即可
    if (messages.value[msgIndex]) messages.value[msgIndex].streaming = false;
    loading.value = false;
    abortController = null;
  };

  const flushTyping = () => {
    // 若这条消息已被重置清掉，停止打字机链，避免访问 undefined 抛 TypeError
    if (!messages.value[msgIndex]) {
      pendingText = '';
      typingTimer = null;
      loading.value = false;
      return;
    }
    if (!pendingText) {
      typingTimer = null;
      finishIfReady();
      return;
    }
    const size = pendingText.length > 160 ? 4 : 2;
    messages.value[msgIndex].content += pendingText.slice(0, size);
    pendingText = pendingText.slice(size);
    scrollToBottom();
    typingTimer = window.setTimeout(flushTyping, 42);
  };

  const enqueueText = (text: string) => {
    if (!text) return;
    pendingText += text;
    if (!typingTimer) flushTyping();
  };

  await api.chatStream(
    { query, route_mode: routeMode.value },
    {
      onChunk: (text) => {
        enqueueText(text);
      },
      onDone: () => {
        streamFinished = true;
        finishIfReady();
      },
      onError: (msg) => {
        const prefix = messages.value[msgIndex].content ? '\n\n' : '';
        messages.value[msgIndex].content += `${prefix}抱歉，出错了：${msg}`;
        pendingText = '';
        if (typingTimer) {
          window.clearTimeout(typingTimer);
          typingTimer = null;
        }
        streamFinished = true;
        finishIfReady();
      },
    },
    abortController.signal
  );
};

const handleSend = async () => {
  await sendQuery(inputText.value.trim());
};

const handleQuickQuestion = async (question: string) => {
  await sendQuery(question);
};

const handleUseQuickQuestion = () => {
  if (!selectedQuickItem.value) return;
  inputText.value = buildQuickQuery(selectedQuickItem.value);
};

const composeModelQuestion = () => {
  const types = selectedModelDataTypes.value.length ? selectedModelDataTypes.value.join('、') : '相关';
  const template = selectedModelPrompt.value || modelPromptOptions.value[0] || '分析近期异常磨损的主要原因，并给出重点关注刀位和处理建议';
  if (/^(结合|综合)/.test(template)) {
    inputText.value = template;
    return;
  }
  inputText.value = `结合${types}数据，${template}`;
};

const handleModelDataTypesChange = () => {
  if (selectedModelPrompt.value && !modelPromptOptions.value.includes(selectedModelPrompt.value)) {
    selectedModelPrompt.value = modelPromptOptions.value[0] || '';
  }
  composeModelQuestion();
};

const handleModelPromptChange = () => {
  composeModelQuestion();
};

const applyModelPrompt = (question: string) => {
  selectedModelPrompt.value = question;
  composeModelQuestion();
};

const applyModelDataType = (type: string) => {
  if (!selectedModelDataTypes.value.includes(type)) selectedModelDataTypes.value.push(type);
  composeModelQuestion();
};

const handleReset = async () => {
  try {
    resetting.value = true;
    // 先中止仍在进行的流式请求，避免 onChunk/打字机继续往已清空的数组里写
    abortController?.abort();
    abortController = null;
    loading.value = false;
    const response = await api.reset();
    messages.value = [];
    ElMessage.success(response.data?.message || '对话已重置');
  } catch (error: any) {
    ElMessage.error('重置失败：' + (error.message || '未知错误'));
  } finally {
    resetting.value = false;
  }
};

onMounted(async () => {
  try {
    const response = await api.health();
    if (response.data?.status) {
      console.log('AI 服务状态：', response.data.status);
    }
  } catch {
    ElMessage.warning('AI 服务连接异常，部分功能可能不可用');
  }
});

onUnmounted(() => {
  abortController?.abort();
});
</script>

<style scoped lang="scss">
.ai-assistant-container {
  height: calc(100vh - 120px);
  padding: 20px;

  .chat-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__header) {
      padding: 16px 20px;
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
        font-size: 18px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 8px;
      }
    }

    .chat-content {
      height: 100%;
      display: flex;
      flex-direction: column;

      .messages-container {
        flex: 1;
        overflow-y: auto;
        padding: 18px 20px;
        background:
          radial-gradient(circle at 20% 0%, rgba(64, 158, 255, 0.08), transparent 28%),
          linear-gradient(180deg, #f8fbff 0%, #f3f6fb 100%);

        .welcome-message {
          text-align: center;
          padding: 60px 20px;
          color: #606266;

          h3 {
            margin: 20px 0 10px;
            font-size: 24px;
            color: #303133;
          }

          p {
            margin: 20px 0 10px;
            font-size: 16px;
          }

          ul {
            text-align: left;
            display: inline-block;
            margin: 0;
            padding-left: 20px;

            li {
              margin: 8px 0;
              font-size: 14px;
            }
          }
        }

        .message-item {
          display: flex;
          margin-bottom: 20px;
          animation: fadeIn 0.3s ease-in;

          &.user {
            flex-direction: row-reverse;

            .message-content {
              align-items: flex-end;
              margin-right: 12px;
              margin-left: 0;

              .message-text {
                background: #409eff;
                color: white;
              }
            }
          }

          &.assistant {
            .message-content {
              margin-left: 12px;
            }
          }

          .message-avatar {
            flex-shrink: 0;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: #e4e7ed;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #909399;
          }

          .message-content {
            max-width: 74%;
            display: flex;
            flex-direction: column;

            .message-text {
              padding: 12px 16px;
              border-radius: 8px;
              background: white;
              box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
              word-break: break-word;
              white-space: pre-wrap;
              line-height: 1.6;

              .plain-answer {
                white-space: pre-wrap;
              }

              .analysis-answer {
                display: flex;
                flex-direction: column;
                gap: 10px;
                white-space: normal;

                .analysis-lead {
                  margin: 0;
                  color: #303133;
                  font-weight: 500;
                  white-space: pre-wrap;
                }

                .analysis-section {
                  border-left: 3px solid #909399;
                  background: #f8fafc;
                  padding: 10px 12px;
                  border-radius: 6px;

                  &.conclusion {
                    border-left-color: #409eff;
                    background: #ecf5ff;
                  }

                  &.evidence {
                    border-left-color: #67c23a;
                    background: #f0f9eb;
                  }

                  &.warning {
                    border-left-color: #e6a23c;
                    background: #fdf6ec;
                  }

                  &.suggestion {
                    border-left-color: #626aef;
                    background: #f4f4ff;
                  }

                  .analysis-section-title {
                    font-weight: 600;
                    color: #303133;
                    margin-bottom: 6px;
                  }

                  p,
                  ul {
                    margin: 0;
                    color: #606266;
                  }

                  ul {
                    padding-left: 18px;
                  }

                  li + li {
                    margin-top: 4px;
                  }
                }
              }

              &.typing {
                display: flex;
                gap: 4px;
                padding: 16px;

                span {
                  width: 8px;
                  height: 8px;
                  border-radius: 50%;
                  background: #909399;
                  animation: typing 1.4s infinite;

                  &:nth-child(2) {
                    animation-delay: 0.2s;
                  }

                  &:nth-child(3) {
                    animation-delay: 0.4s;
                  }
                }
              }
            }

            .message-time {
              font-size: 12px;
              color: #909399;
              margin-top: 4px;
              padding: 0 4px;
            }
          }
        }
      }

      .input-container {
        border-top: 1px solid #ebeef5;
        padding: 10px 16px 14px;
        background: rgba(255, 255, 255, 0.96);
        box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.06);

        .route-switch {
          display: inline-flex;
          gap: 4px;
          margin-bottom: 6px;
          padding: 2px;
          border: 1px solid #d7dfeb;
          border-radius: 999px;
          background: #eef3f9;
        }

        .route-option {
          min-width: 104px;
          height: 28px;
          border: 0;
          border-radius: 999px;
          background: transparent;
          color: #606266;
          cursor: pointer;
          font-size: 13px;
          line-height: 1;
        }

        .route-option span {
          display: block;
          margin-top: 3px;
          font-size: 11px;
          color: #909399;
        }

        .route-option.active {
          background: #ffffff;
          color: #303133;
          box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
        }

        .route-option.active span {
          color: #409eff;
        }

        .prompt-dock {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 6px;
          min-height: 34px;
          padding: 5px 7px;
          border: 1px solid #d7dfeb;
          border-radius: 10px;
          background: linear-gradient(180deg, #ffffff 0%, #f7faff 100%);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
        }

        .prompt-dock.model {
          align-items: center;
        }

        .dock-label {
          flex-shrink: 0;
          color: #64748b;
          font-size: 12px;
          font-weight: 600;
          padding: 0 4px;
        }

        .mode-select {
          width: 168px;
          flex-shrink: 0;
        }

        .question-select {
          flex: 1;
          min-width: 300px;
        }

        .quick-number {
          width: 92px;
          flex-shrink: 0;
        }

        .quick-run {
          flex-shrink: 0;
        }

        .model-capability-select {
          width: 300px;
          flex-shrink: 0;
        }

        .model-prompt-select {
          flex: 1;
          min-width: 280px;
          flex-shrink: 0;
        }

        @media (max-width: 900px) {
          .prompt-dock,
          .prompt-dock.model {
            align-items: stretch;
            flex-direction: column;
          }

          .mode-select,
          .question-select,
          .quick-number,
          .model-capability-select,
          .model-prompt-select {
            width: 100%;
            min-width: 0;
          }
        }

        .input-actions {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-top: 12px;

          .input-tip {
            font-size: 12px;
            color: #909399;
          }
        }
      }
    }
  }

}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes typing {
  0%,
  60%,
  100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-10px);
  }
}
</style>
