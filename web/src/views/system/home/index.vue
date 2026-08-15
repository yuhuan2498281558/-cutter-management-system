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
      <button class="overview-toggle" @click="overviewMode = true">
        换刀展示
      </button>
      <button class="mapper-toggle" @click="mapperMode = !mapperMode">
        {{ mapperMode ? '退出匹配' : '刀位匹配' }}
      </button>
      <BimfaceMapper v-if="mapperMode" @close="mapperMode = false" />
      <BimfaceModel v-else />
      <!-- 手动标注工具: <CutterheadMapper /> -->
      <!-- 自动标注工具: <CutterheadMapperAuto /> -->
      <!-- 旧版2D模型: <CutterheadModel2D /> -->
      <!-- 旧版3D模型: <CutterheadModelPro /> -->
      <!-- 旧版简易模型: <CutterheadModel /> -->
      <!-- <div ref="bimContainer" class="bim-container w-full h-full rounded-lg border border-gray-200 shadow-sm"></div> -->
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, reactive } from 'vue';
// 保留原组件：项目简介；新增组件：刀具信息
import ProjectInfoCard from './projectintroduction.vue';
import ToolInfo from './toolinfo.vue';
import CutterheadImage from './CutterheadImage.vue';
import BimfaceModel from './BimfaceModel.vue';
import BimfaceMapper from './BimfaceMapper.vue';
import LeftPanel from './LeftPanel.vue';
import ToolChangeOverview from './ToolChangeOverview.vue';
// import CutterheadMapper from './CutterheadMapper.vue'; // 手动刀位标注工具
// import CutterheadMapperAuto from './CutterheadMapperAuto.vue'; // 自动化刀位标注工具
// import CutterheadModel2D from './CutterheadModel2D.vue'; // 旧版2D刀盘模型
// import CutterheadModelPro from './CutterheadModelPro.vue'; // 旧版3D刀盘模型（已弃用）
// import CutterheadModel from './CutterheadModel.vue'; // 旧版简易刀盘模型（已弃用）

// ---------------------- 工具函数：获取当前日期并格式化 ----------------------
const getCurrentDate = () => {
  const date = new Date();
  // 格式化日期为 "YYYY-MM-DD" 格式
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0'); // 月份从0开始，需+1
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

// ---------------------- BIMFACE 核心配置（已替换为简易刀盘模型） ----------------------
// let bimViewer = null;
// let bimApp = null;
// const bimContainer = ref(null);
// const bimViewToken = 'fa4f3d81d0f841b08079ae31a899647f'; // 替换为实际BIMFACE视图令牌
const bimTitle = ref('盾构机刀盘模型');
const mapperMode = ref(false);
const overviewMode = ref(false);

// Ctrl+Shift+M 切换标定工具
function onKeydown(e) {
  if (e.ctrlKey && e.shiftKey && e.key === 'M') {
    mapperMode.value = !mapperMode.value;
  }
}

const showEdit = ref(true);
const titleStyle = ref('');

// 编辑BIM标题方法
const editTitle = () => {
  const newTitle = prompt('请输入新的模型标题', bimTitle.value);
  if (newTitle?.trim()) {
    bimTitle.value = newTitle.trim();
  }
};

// ---------------------- 项目简介数据（保留原数据） ----------------------
const projectDetails = ref({
  name: '智慧盾构机刀具管理监测项目', // 项目名称调整为盾构机相关
  address: '福建省福州市', // 地址适配盾构机场景
  area: '盾构机总长1.2公里', // 数据调整为盾构机维度
  description: '本项目为智慧盾构机刀具管理监测系统，基于BIM技术构建盾构机全生命周期模型，结合传感器实时监测数据，实现盾构机结构健康状态可视化管理。支持模型查看、刀具信息查询、预警分析等功能，助力盾构机运维决策。',
  updateDate: getCurrentDate()
});

// 项目卡片展开/收起状态
const cardExpanded = ref(true);
const toggleExpanded = (expanded) => {
  cardExpanded.value = expanded;
};

// ---------------------- 刀具信息数据（预留API对接入口） ----------------------
const toolData = ref([]); // 刀具档案列表数据

// 模拟获取刀具数据（后续可替换为真实API请求）
const fetchToolData = async () => {
  try {
    // 此处替换为真实API：如 axios.get('/api/tool-archive')
    // 示例模拟数据（与刀具档案表字段匹配）
    const mockToolData = [
      {
        toolId: 'TOOL-20250701-001', // 刀具ID
        toolName: '盾构机切削刀', // 刀具名称
        model: 'TC-800A', // 刀具型号
        specification: '直径12mm，长度80mm', // 规格参数
        manufacturer: '上海精密工具厂', // 生产厂家
        purchaseDate: '2025-01-15', // 采购日期
        serviceLife: '500小时', // 使用寿命
        currentStatus: '正常使用', // 当前状态（正常/维修/报废）
        lastMaintainDate: '2025-06-20', // 上次维护日期
        operator: '张三' // 操作人员
      },
      {
        toolId: 'TOOL-20250701-002',
        toolName: '盾构机打磨刀',
        model: 'DM-500B',
        specification: '直径20mm，长度100mm',
        manufacturer: '苏州五金工具有限公司',
        purchaseDate: '2025-02-20',
        serviceLife: '800小时',
        currentStatus: '待维护',
        lastMaintainDate: '2025-05-10',
        operator: '李四'
      }
    ];
    toolData.value = mockToolData;
  } catch (error) {
    console.error('获取刀具档案数据失败:', error);
  }
};

// ---------------------- BIMFACE 初始化（已替换为简易刀盘模型，暂时注释） ----------------------
/*
const initBimViewer = async () => {
  if (!bimContainer.value) return;

  try {
    // 动态加载BIMFACE SDK
    const script = document.createElement('script');
    script.src = 'https://static.bimface.com/api/BimfaceSDKLoader/BimfaceSDKLoader@latest-release.js';
    script.charset = 'utf-8';
    script.onload = () => {
      const loaderConfig = new window.BimfaceSDKLoaderConfig();
      loaderConfig.viewToken = bimViewToken;

      window.BimfaceSDKLoader.load(
        loaderConfig,
        bimSuccessCallback,
        bimFailureCallback
      );
    };
    document.body.appendChild(script);
  } catch (error) {
    console.error('加载BIMFACE SDK失败:', error);
  }
};

// BIM加载成功回调（优化模型显示适配）
const bimSuccessCallback = (viewMetaData) => {
  const webAppConfig = new window.Glodon.Bimface.Application.WebApplication3DConfig();
  webAppConfig.domElement = bimContainer.value;
  // 新增BIM视图配置：默认显示桥梁整体，开启旋转/缩放控制
  webAppConfig.controls = {
    enableRotate: true,
    enableZoom: true,
    enablePan: true
  };
  bimApp = new window.Glodon.Bimface.Application.WebApplication3D(webAppConfig);
  bimApp.addView(bimViewToken);
  bimViewer = bimApp.getViewer();

  // 可选：设置BIM模型初始视角（聚焦桥梁主体）
  if (bimViewer) {
    bimViewer.setViewpoint({
      position: [100, 100, 50], // 可根据实际模型调整坐标
      target: [0, 0, 0]
    });
  }
};

// BIM加载失败回调
const bimFailureCallback = (error) => {
  console.error('BIMFACE加载失败:', error);
  // 新增错误提示：用户可直观看到失败信息
  if (bimContainer.value) {
    bimContainer.value.innerHTML = `
      <div class="flex items-center justify-center h-full text-red-500">
        <i class="fa fa-exclamation-circle mr-2"></i>
        盾构机模型加载失败，请检查视图令牌或网络连接
      </div>
    `;
  }
};
*/

// ---------------------- 组件生命周期（优化资源清理） ----------------------
onMounted(async () => {
  await nextTick();
  fetchToolData();
  window.addEventListener('keydown', onKeydown);
  setInterval(() => {
    projectDetails.value.updateDate = getCurrentDate();
  }, 86400000); // 24小时（86400000毫秒）更新一次
});


onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown);
  /*
  if (bimApp && bimApp.destroy) {
    bimApp.destroy();
    bimApp = null;
    bimViewer = null;
  }
  // 清除BIMFACE SDK脚本（避免内存泄漏）
  const bimScript = document.querySelector('script[src*="BimfaceSDKLoader"]');
  if (bimScript) bimScript.remove();
  */
});
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

.overview-back {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 80;
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgba(20, 33, 49, 0.18);
  border-radius: 6px;
  background: #142131;
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.overview-back:hover {
  background: #24364d;
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

.overview-toggle {
  position: absolute;
  top: 12px;
  right: 116px;
  z-index: 60;
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgba(255,255,255,0.28);
  border-radius: 6px;
  background: rgba(20, 33, 49, 0.86);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.overview-toggle:hover {
  background: rgba(36, 54, 77, 0.94);
}

.mapper-toggle {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 60;
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgba(255,255,255,0.28);
  border-radius: 6px;
  background: rgba(20, 33, 49, 0.86);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.mapper-toggle:hover {
  background: rgba(36, 54, 77, 0.94);
}

/* BIM模型容器：占满右侧空间，优化边框和阴影 */
.bim-container {
  width: 100%;
  height: 100%;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  overflow: hidden;
}

/* 刀具信息容器：优化内边距和分隔线 */
.tool-info-container {
  padding: 6px;
  border-top: 1px dashed #e5e7eb; /* 与项目简介模块分隔 */
  margin-top: 4px;
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
