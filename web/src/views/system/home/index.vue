<template>
  <div v-if="overviewMode" class="tool-change-page">
    <ToolChangeOverview @back="overviewMode = false" />
  </div>
  <div v-else class="bim-gis-container">
    <!-- BIM 标题覆盖层 -->
    <div
      v-if="bimTitle"
      class="absolute top-4 left-1/2 transform -translate-x-1/2 z-10 transition-all duration-300"
      :class="titleStyle"
    >
      <div class="bg-blue-800/70 text-white px-4 py-2 rounded-lg shadow-lg flex items-center">
        <i class="fa fa-bridge mr-2"></i> <!-- 图标替换为桥梁相关 -->
        <h2 class="text-xl font-bold">{{ bimTitle }}</h2>
        <button
          v-if="showEdit"
          @click="editTitle"
          class="ml-4 text-sm bg-white/20 hover:bg-white/30 px-2 py-1 rounded transition-colors"
        >
          <i class="fa fa-pencil"></i> 编辑
        </button>
      </div>
    </div>

    <!-- 左侧边栏 -->
    <div class="sidebar">
      <LeftPanel />
    </div>

    <!-- 右侧主内容：全屏桥梁BIM模型展示（删除地图后替换为BIM容器） -->
    <div class="main-content">
      <div class="home-actions">
        <button @click="overviewMode = true">换刀展示</button>
      </div>
      <BimfaceModel />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import BimfaceModel from './BimfaceModel.vue';
import LeftPanel from './LeftPanel.vue';
import ToolChangeOverview from './ToolChangeOverview.vue';

const bimTitle = ref('盾构机刀盘模型');
const overviewMode = ref(false);

const showEdit = ref(true);
const titleStyle = ref('');

// 编辑BIM标题方法
const editTitle = () => {
  const newTitle = prompt('请输入新的模型标题', bimTitle.value);
  if (newTitle?.trim()) {
    bimTitle.value = newTitle.trim();
  }
};
</script>

<style scoped>
/* 整体布局：左侧边栏 + 右侧BIM模型 */
.bim-gis-container {
  display: flex;
  height: 100vh;
  position: relative;
  overflow: hidden; /* 避免页面滚动 */
}

.tool-change-page {
  height: 100vh;
  position: relative;
  overflow: hidden;
  background: #f3f5f8;
}

/* 左侧边栏：固定宽度，垂直分布项目简介和刀具信息 */
.sidebar {
  width: 600px;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden;
  background-color: #f4f5f9;
  box-shadow: 2px 0 4px rgba(0,0,0,0.05);
}

/* 右侧主内容：全屏BIM模型容器 */
.main-content {
  flex: 2;
  height: 100%;
  box-sizing: border-box;
  position: relative;
}

.home-actions {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 60;
  display: flex;
  gap: 8px;
}

.home-actions button {
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgba(255,255,255,0.28);
  border-radius: 6px;
  background: rgba(20, 33, 49, 0.86);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.home-actions button:hover,
.home-actions button.active {
  background: rgba(36, 54, 77, 0.94);
}

/* 响应式适配：小屏幕下调整布局 */
@media (max-width: 1200px) {
  .sidebar {
    width: 280px;
  }
}

@media (max-width: 768px) {
  .bim-gis-container {
    flex-direction: column;
  }
  .sidebar {
    width: 100%;
    height: auto;
    max-height: 40vh;
  }
  .main-content {
    height: 60vh;
  }
}
</style>
