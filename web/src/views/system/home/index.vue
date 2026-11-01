<template>
  <div v-if="overviewMode" class="tool-change-page">
    <ToolChangeOverview @back="overviewMode = false" />
  </div>
  <div v-else class="bim-gis-container">
    <!-- 左侧边栏 -->
    <div class="sidebar">
      <LeftPanel />
    </div>

    <!-- 右侧主内容：上方标题栏 + 下方BIM模型 -->
    <div class="main-content">
      <!-- 标题和按钮放在模型上方，不叠在模型上：模型四角都有 BIMFace 自带的控件（左上目录树、右上视图方块、下方工具栏） -->
      <div class="model-header">
        <h2 v-if="bimTitle" :class="titleStyle">{{ bimTitle }}</h2>
        <button v-if="showEdit" type="button" class="model-title-edit" @click="editTitle">
          <i class="fa fa-pencil"></i> 编辑
        </button>
        <button type="button" class="model-action" @click="overviewMode = true">换刀展示</button>
      </div>
      <div class="model-stage">
        <BimfaceModel />
      </div>
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
/* 整体布局：左侧边栏 + 右侧BIM模型
 * 高度用主内容区可用高度（减掉顶栏和页脚，见 theme/app.scss 的 --dv-main-height），写 100vh 会多出顶栏那一截、底部被挤出屏幕 */
.bim-gis-container {
  display: flex;
  height: var(--dv-main-height);
  position: relative;
  overflow: hidden; /* 避免页面滚动 */
}

.tool-change-page {
  height: var(--dv-main-height);
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

/* 右侧主内容：标题栏 + 模型区，模型区占满剩下的高度 */
.main-content {
  flex: 2;
  min-width: 0;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

/* 模型上方的标题栏：左边标题和"编辑"，右边"换刀展示" */
.model-header {
  flex-shrink: 0;
  height: 48px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px 0 16px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--dv-border);
  background: var(--dv-surface);
  color: var(--dv-text);
}

.model-header h2 {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--dv-font-title);
  font-size: 16px;
  font-weight: 600;
  line-height: 1;
}

.model-title-edit {
  flex-shrink: 0;
  height: 24px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--dv-radius-sm);
  background: transparent;
  color: var(--dv-text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.model-title-edit:hover {
  background: var(--dv-hover);
  color: var(--dv-text);
}

.model-action {
  flex-shrink: 0;
  margin-left: auto;
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--dv-border-strong);
  border-radius: var(--dv-radius);
  background: var(--dv-surface);
  color: var(--dv-text);
  font-size: 13px;
  cursor: pointer;
}

.model-action:hover {
  background: var(--dv-hover);
}

/* 模型区：BimfaceModel 绝对定位铺满这一块 */
.model-stage {
  flex: 1;
  min-height: 0;
  position: relative;
}

/* 响应式适配：小屏幕下调整布局 */
@media (max-width: 1200px) {
  .sidebar {
    width: 280px;
  }
}

@media (max-width: 768px) {
  /* 上下排：项目面板 40vh + 模型 60vh，比主内容区高，交给主内容区滚动 */
  .bim-gis-container {
    flex-direction: column;
    height: auto;
    overflow: visible;
  }
  .sidebar {
    width: 100%;
    height: auto;
    max-height: 40vh;
  }
  /* 容器高度不固定时 flex: 2 会按内容算高，模型区（全是绝对定位）就塌成 0，这里改成固定高度 */
  .main-content {
    flex: none;
    height: 60vh;
  }
}
</style>
