<template>
  <div class="tool-info-card bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
    <!-- 组件头部：标题 + 刷新按钮 -->
    <div class="tool-header px-4 py-3 border-b border-gray-200 flex justify-between items-center">
      <span class="text-sm font-medium text-gray-600">刀具档案列表</span>
      <button
        @click="$emit('refreshToolData')"
        class="text-xs text-blue-600 hover:text-blue-800 flex items-center transition-colors"
      >
        <i class="fa fa-refresh mr-1"></i> 刷新
      </button>
    </div>

    <!-- 刀具数据表格 -->
    <div class="tool-table-container overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="bg-gray-50 text-left text-gray-600">
            <th class="px-4 py-2 font-medium">刀具ID</th>
            <th class="px-4 py-2 font-medium">刀具名称</th>
            <th class="px-4 py-2 font-medium">型号</th>
            <th class="px-4 py-2 font-medium">当前状态</th>
            <th class="px-4 py-2 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          <!-- 无数据状态 -->
          <tr v-if="!toolList.length">
            <td colspan="5" class="px-4 py-8 text-center text-gray-500">
              <i class="fa fa-folder-open-o mr-2"></i>暂无刀具档案数据
            </td>
          </tr>
          <!-- 有数据状态 -->
          <tr
            v-for="(tool, index) in toolList"
            :key="index"
            class="border-t border-gray-100 hover:bg-gray-50 transition-colors"
          >
            <td class="px-4 py-3 text-gray-800">{{ tool.toolId }}</td>
            <td class="px-4 py-3 text-gray-800">{{ tool.toolName }}</td>
            <td class="px-4 py-3 text-gray-800">{{ tool.model }}</td>
            <!-- 状态标签：根据状态显示不同颜色 -->
            <td class="px-4 py-3">
              <span
                :class="getStatusTagClass(tool.currentStatus)"
                class="px-2 py-1 rounded-full text-xs font-medium"
              >
                {{ tool.currentStatus }}
              </span>
            </td>
            <!-- 操作按钮：查看详情（可扩展编辑/删除） -->
            <td class="px-4 py-3">
              <button
                @click="showToolDetail(tool)"
                class="text-blue-600 hover:text-blue-800 transition-colors"
                title="查看详情"
              >
                <i class="fa fa-eye"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 刀具详情弹窗（默认隐藏） -->
    <teleport to="body">
      <div
        v-if="showDetailModal"
        class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
        @click.self="closeDetailModal"
      >
        <div class="bg-white rounded-lg shadow-lg w-full max-w-2xl max-h-[80vh] overflow-auto">
          <!-- 弹窗头部 -->
          <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
            <h4 class="text-lg font-bold text-gray-800">刀具详情 - {{ currentTool.toolId }}</h4>
            <button
              @click="closeDetailModal"
              class="text-gray-500 hover:text-gray-700 transition-colors"
            >
              <i class="fa fa-times"></i>
            </button>
          </div>
          <!-- 弹窗内容：刀具完整信息 -->
          <div class="px-6 py-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">刀具名称</span>
                <span class="text-gray-800">{{ currentTool.toolName }}</span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">刀具型号</span>
                <span class="text-gray-800">{{ currentTool.model }}</span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">规格参数</span>
                <span class="text-gray-800">{{ currentTool.specification }}</span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">生产厂家</span>
                <span class="text-gray-800">{{ currentTool.manufacturer }}</span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">采购日期</span>
                <span class="text-gray-800">{{ currentTool.purchaseDate }}</span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">使用寿命</span>
                <span class="text-gray-800">{{ currentTool.serviceLife }}</span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">当前状态</span>
                <span
                  :class="getStatusTagClass(currentTool.currentStatus)"
                  class="inline-block px-2 py-1 rounded-full text-xs font-medium mt-1"
                >
                  {{ currentTool.currentStatus }}
                </span>
              </div>
              <div class="flex flex-col">
                <span class="text-xs text-gray-500 mb-1">上次维护日期</span>
                <span class="text-gray-800">{{ currentTool.lastMaintainDate }}</span>
              </div>
              <div class="flex flex-col md:col-span-2">
                <span class="text-xs text-gray-500 mb-1">操作人员</span>
                <span class="text-gray-800">{{ currentTool.operator }}</span>
              </div>
            </div>
          </div>
          <!-- 弹窗底部 -->
          <div class="px-6 py-4 border-t border-gray-200 flex justify-end">
            <button
              @click="closeDetailModal"
              class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-800 rounded-lg transition-colors"
            >
              关闭
            </button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, defineProps, defineEmits } from 'vue';

// 定义组件属性：接收刀具列表数据
const props = defineProps({
  toolList: {
    type: Array,
    default: () => [],
    required: true
  }
});

// 定义组件事件：触发刷新数据
const emit = defineEmits(['refreshToolData']);

// 弹窗相关状态
const showDetailModal = ref(false);
const currentTool = ref({});

// 根据刀具状态返回标签样式
const getStatusTagClass = (status) => {
  switch (status) {
    case '正常使用':
      return 'bg-green-100 text-green-800';
    case '待维护':
      return 'bg-yellow-100 text-yellow-800';
    case '维修中':
      return 'bg-blue-100 text-blue-800';
    case '报废':
      return 'bg-red-100 text-red-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
};

// 显示刀具详情
const showToolDetail = (tool) => {
  currentTool.value = { ...tool }; // 深拷贝避免数据联动
  showDetailModal.value = true;
};

// 关闭详情弹窗
const closeDetailModal = () => {
  showDetailModal.value = false;
  currentTool.value = {};
};
</script>

<style scoped>
/* 表格样式优化 */
.tool-table-container {
  max-height: 400px; /* 限制表格高度，避免超出页面 */
  overflow-y: auto;
}

/* 滚动条样式优化 */
.tool-table-container::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.tool-table-container::-webkit-scrollbar-thumb {
  background-color: #e5e7eb;
  border-radius: 3px;
}

.tool-table-container::-webkit-scrollbar-track {
  background-color: #f9fafb;
}

/* 弹窗动画 */
.fixed.inset-0 {
  animation: fadeIn 0.3s ease-in-out;
}

.fixed.inset-0 > div {
  animation: slideUp 0.3s ease-in-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
</style>